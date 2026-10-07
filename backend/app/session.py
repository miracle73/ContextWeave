"""Realtime interview session: transcript revisions, debounced provisional answers, cancellation, final answers.

Invariants:
- Every transcript update bumps `revision`.
- Every generation gets a unique `gen_id`; only the active generation may emit tokens.
- Starting a new generation cancels the previous one (and tells the client).
- Final transcript (utterance end) always produces a complete answer for the full question text.
"""

import asyncio
import contextlib
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from . import agent
from .llm import LLM, LLMError
from .store import Chat, Turn

Send = Callable[[dict], Awaitable[None]]


@dataclass
class SessionConfig:
    debounce_s: float = 0.7
    min_words: int = 5
    min_new_words: int = 3
    max_provisional: int = 3
    min_provisional_gap_s: float = 1.5
    generations_per_minute: int = 20


@dataclass
class Generation:
    id: str
    revision: int
    question: str
    provisional: bool
    text: str = ""
    done: bool = False
    task: asyncio.Task | None = field(default=None, repr=False)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", text.lower()))


class InterviewSession:
    def __init__(self, chat: Chat, llm: LLM, send: Send, model: str, length: str = "medium",
                 cfg: SessionConfig | None = None) -> None:
        self.chat, self.llm, self.send = chat, llm, send
        self.model, self.length = model, length
        self.cfg = cfg or SessionConfig()
        self.revision = 0
        self.committed = ""
        self.interim = ""
        self.gen_seq = 0
        self.active: Generation | None = None
        self.last_provisional: Generation | None = None
        self.provisional_count = 0
        self.last_provisional_at = 0.0
        self._debounce: asyncio.Task | None = None
        self._gen_times: deque[float] = deque()

    @property
    def text(self) -> str:
        return " ".join(s for s in (self.committed, self.interim) if s).strip()

    # ---- transcript input -------------------------------------------------
    async def on_transcript(self, text: str, is_final: bool, utterance_end: bool = False) -> None:
        text = text.strip()[:2000]
        self.revision += 1
        if is_final and not text and utterance_end:
            # Utterance ended without a final segment: the latest interim is the best hypothesis.
            self.committed = self.text
            self.interim = ""
        elif is_final:
            if text:
                self.committed = f"{self.committed} {text}".strip()
            self.interim = ""
        else:
            self.interim = text
        await self.send({"type": "transcript", "revision": self.revision, "committed": self.committed,
                         "interim": self.interim, "text": self.text, "is_final": is_final})
        if utterance_end:
            await self.end_utterance()
        else:
            self._schedule_provisional()

    def _schedule_provisional(self) -> None:
        if len(agent.words(self.text)) < self.cfg.min_words:
            return
        if self._debounce and not self._debounce.done():
            self._debounce.cancel()
        self._debounce = asyncio.create_task(self._debounced(self.revision))

    async def _debounced(self, rev: int) -> None:
        await asyncio.sleep(self.cfg.debounce_s)
        self._debounce = None  # past this point end_utterance must not cancel us mid-start
        if rev != self.revision:
            return
        text = self.text
        if not self._worth_provisional(text):
            return
        self.provisional_count += 1
        self.last_provisional_at = time.monotonic()
        await self._start(text, provisional=True)

    def _worth_provisional(self, text: str) -> bool:
        if self.provisional_count >= self.cfg.max_provisional:
            return False
        if time.monotonic() - self.last_provisional_at < self.cfg.min_provisional_gap_s:
            return False
        prev = self.last_provisional.question if self.last_provisional else ""
        new_words = len(agent.words(text)) - len(agent.words(prev)) if _norm(text).startswith(_norm(prev)) else 99
        if prev and new_words < self.cfg.min_new_words:
            return False
        return agent.detect_question(text) or len(agent.words(text)) >= 8

    async def end_utterance(self) -> None:
        """Final transcript: produce a complete answer reflecting the whole question."""
        if self._debounce and not self._debounce.done():
            self._debounce.cancel()
        self._debounce = None
        text = self.text
        self.committed = self.interim = ""
        prov = self.last_provisional
        self.provisional_count, self.last_provisional, self.last_provisional_at = 0, None, 0.0
        if not text:
            return
        if not agent.detect_question(text):
            await self.cancel("not_a_question")
            await self.send({"type": "no_question", "revision": self.revision, "text": text})
            return
        # A finished provisional answer for the identical question can be promoted without another API call.
        if prov and prov.done and prov is self.active and _norm(prov.question) == _norm(text):
            await self._finalise(prov)
            return
        await self._start(text, provisional=False)

    async def ask_text(self, text: str) -> None:
        """Typed question (text fallback): always a final answer."""
        if self._debounce and not self._debounce.done():
            self._debounce.cancel()
        self.committed = self.interim = ""
        self.provisional_count, self.last_provisional = 0, None
        text = text.strip()[:2000]
        if text:
            self.revision += 1
            await self._start(text, provisional=False)

    # ---- generations ------------------------------------------------------
    def _rate_ok(self) -> bool:
        now = time.monotonic()
        while self._gen_times and now - self._gen_times[0] > 60:
            self._gen_times.popleft()
        if len(self._gen_times) >= self.cfg.generations_per_minute:
            return False
        self._gen_times.append(now)
        return True

    async def cancel(self, reason: str = "cancelled") -> None:
        gen, self.active = self.active, None
        if gen and not gen.done:
            if gen.task:
                gen.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await gen.task
            await self.send({"type": "answer_cancelled", "gen_id": gen.id, "reason": reason})

    async def _start(self, question: str, provisional: bool) -> None:
        if not self._rate_ok():
            if not provisional:
                await self.send({"type": "error", "code": "rate_limited",
                                 "message": "Too many answers this minute; wait a moment."})
            return
        await self.cancel("superseded")
        self.gen_seq += 1
        gen = Generation(f"g{self.gen_seq}", self.revision, question, provisional)
        self.active = gen
        if provisional:
            self.last_provisional = gen
        gen.task = asyncio.create_task(self._run(gen))

    async def _run(self, gen: Generation) -> None:
        try:
            p = agent.plan(gen.question, self.chat)
            await self.send({"type": "answer_start", "gen_id": gen.id, "revision": gen.revision,
                             "provisional": gen.provisional, "question": gen.question, "kind": p.kind,
                             "follow_up": p.follow_up, "missing_evidence": p.missing_evidence,
                             "evidence": [{k: e[k] for k in ("id", "source", "score")} | {"snippet": e["text"][:200]}
                                          for e in p.evidence]})
            messages, max_tokens = agent.build_messages(p, self.chat, self.length, gen.provisional)
            async for delta in self.llm.stream(messages, self.model, max_tokens):
                if self.active is not gen:  # stale: a newer generation owns the stream
                    return
                gen.text += delta
                await self.send({"type": "token", "gen_id": gen.id, "delta": delta})
            if self.active is not gen:
                return
            gen.done = True
            if gen.provisional:
                await self.send({"type": "answer_end", "gen_id": gen.id, "final": False, "text": gen.text})
            else:
                await self._finalise(gen)
        except asyncio.CancelledError:
            raise
        except LLMError as e:
            if self.active is gen:
                gen.done, self.active = True, None
                await self.send({"type": "error", "gen_id": gen.id, "code": e.code, "message": e.message,
                                 "retry_after": e.retry_after})
        except Exception as e:  # noqa: BLE001
            if self.active is gen:
                gen.done, self.active = True, None
                await self.send({"type": "error", "gen_id": gen.id, "code": "internal", "message": str(e)[:200]})

    async def _finalise(self, gen: Generation) -> None:
        self.active = None
        self.chat.history.append(Turn(gen.question, gen.text))
        self.chat.save()
        await self.send({"type": "answer_end", "gen_id": gen.id, "final": True, "text": gen.text,
                         "question": gen.question})

    def snapshot(self) -> dict:
        """Current live state, so a device joining mid-question sees the same thing as the others."""
        g = self.active
        return {"revision": self.revision, "committed": self.committed, "interim": self.interim,
                "model": self.model, "length": self.length,
                "generation": g and {"gen_id": g.id, "revision": g.revision, "provisional": g.provisional,
                                     "question": g.question, "text": g.text, "done": g.done}}

    async def close(self) -> None:
        if self._debounce:
            self._debounce.cancel()
        await self.cancel("closed")
