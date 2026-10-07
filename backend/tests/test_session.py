import asyncio

import pytest

from app.llm import LLMError
from app.session import InterviewSession, SessionConfig
from app.store import ChatStore

FAST = SessionConfig(debounce_s=0.05, min_provisional_gap_s=0, generations_per_minute=100)


class FakeLLM:
    """Streams a deterministic answer echoing the question, slowly enough to be interrupted."""

    def __init__(self, delay: float = 0.02, error: LLMError | None = None):
        self.calls: list[str] = []
        self.delay, self.error = delay, error

    async def stream(self, messages, model, max_tokens):
        q = messages[-1]["content"].split("Interviewer: ")[-1]
        self.calls.append(q)
        if self.error:
            raise self.error
        for w in f"ANSWER[{q}]".split(" "):
            await asyncio.sleep(self.delay)
            yield w + " "


def make(llm=None, cfg=FAST):
    chat = ChatStore().create("t")
    chat.add_source("cv", "cv.pdf", "I led the migration of the billing service to Kubernetes at Acme in 2022.")
    events: list[dict] = []

    async def send(m):
        events.append(m)

    s = InterviewSession(chat, llm or FakeLLM(), send, "m", "short", cfg)
    return s, events, chat


def of(events, t):
    return [e for e in events if e["type"] == t]


async def settle(s):
    quiet = 0
    for _ in range(300):
        await asyncio.sleep(0.01)
        quiet = quiet + 1 if (s.active is None or s.active.done) and not s._debounce else 0
        if quiet >= 5:
            return


@pytest.mark.asyncio
async def test_interim_revisions_are_monotonic_and_debounced():
    s, ev, _ = make()
    for part in ["Tell me", "Tell me about a", "Tell me about a time you", "Tell me about a time you led a migration"]:
        await s.on_transcript(part, is_final=False)
    await settle(s)
    revs = [e["revision"] for e in of(ev, "transcript")]
    assert revs == sorted(revs) and len(set(revs)) == 4
    # rapid fragments collapse into ONE provisional generation for the latest text
    assert len(s.llm.calls) == 1
    start = of(ev, "answer_start")[0]
    assert start["provisional"] and start["revision"] == 4
    assert start["question"].endswith("led a migration")


@pytest.mark.asyncio
async def test_short_fragments_do_not_call_llm():
    s, ev, _ = make()
    await s.on_transcript("So", False)
    await s.on_transcript("So um", False)
    await settle(s)
    assert s.llm.calls == []


@pytest.mark.asyncio
async def test_revision_cancels_outdated_generation_and_drops_stale_tokens():
    s, ev, _ = make(FakeLLM(delay=0.05))
    await s.on_transcript("Tell me about a time you handled a conflict", False)
    await asyncio.sleep(0.12)  # provisional g1 is streaming
    assert s.active and s.active.id == "g1"
    await s.on_transcript("Tell me about a time you handled a conflict with your manager about scope", False)
    await settle(s)
    cancelled = of(ev, "answer_cancelled")
    assert [c["gen_id"] for c in cancelled] == ["g1"]
    idx = ev.index(cancelled[0])
    assert not any(e["type"] == "token" and e["gen_id"] == "g1" for e in ev[idx:]), "stale tokens after cancel"
    assert of(ev, "answer_end")[-1]["gen_id"] == "g2"


@pytest.mark.asyncio
async def test_final_transcript_produces_complete_answer_for_full_question():
    s, ev, chat = make()
    await s.on_transcript("Can you walk me through", False)
    await s.on_transcript("Can you walk me through the Kubernetes migration", True)
    await s.on_transcript("and what you would do differently?", True, utterance_end=True)
    await settle(s)
    end = of(ev, "answer_end")[-1]
    full = "Can you walk me through the Kubernetes migration and what you would do differently?"
    assert end["final"] and end["question"] == full
    assert full in end["text"]
    assert chat.history[-1].question == full
    assert s.text == ""  # transcript reset for next question


@pytest.mark.asyncio
async def test_final_reuses_completed_identical_provisional():
    s, ev, chat = make()
    q = "What did you do at Acme with Kubernetes?"
    await s.on_transcript(q, False)
    await settle(s)
    assert len(s.llm.calls) == 1
    await s.on_transcript("", True, utterance_end=True)
    await settle(s)
    assert len(s.llm.calls) == 1  # promoted, no extra API call
    assert of(ev, "answer_end")[-1]["final"] and chat.history[-1].question == q


@pytest.mark.asyncio
async def test_non_question_utterance_does_not_answer():
    s, ev, chat = make()
    await s.on_transcript("Okay great thanks", True, utterance_end=True)
    await settle(s)
    assert of(ev, "no_question") and not chat.history and s.llm.calls == []


@pytest.mark.asyncio
async def test_provisional_cap_per_utterance():
    s, ev, _ = make(cfg=SessionConfig(debounce_s=0.01, min_provisional_gap_s=0, max_provisional=2))
    base = "Tell me about your experience with"
    for extra in ["distributed systems at scale", "distributed systems at scale and how you tested them",
                  "distributed systems at scale and how you tested them under heavy production load today"]:
        await s.on_transcript(f"{base} {extra}", False)
        await settle(s)
    assert len(s.llm.calls) == 2


@pytest.mark.asyncio
async def test_provider_error_is_reported():
    s, ev, chat = make(FakeLLM(error=LLMError("rate_limited", "slow down", 3)))
    await s.ask_text("What is your biggest strength?")
    await settle(s)
    err = of(ev, "error")[0]
    assert err["code"] == "rate_limited" and err["retry_after"] == 3 and not chat.history


@pytest.mark.asyncio
async def test_session_rate_limit():
    s, ev, _ = make(cfg=SessionConfig(generations_per_minute=1))
    await s.ask_text("What is your biggest strength?")
    await settle(s)
    await s.ask_text("What is your biggest weakness?")
    await settle(s)
    assert len(s.llm.calls) == 1 and of(ev, "error")[0]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_follow_up_includes_history():
    llm = FakeLLM()
    s, ev, chat = make(llm)
    captured = []
    orig = llm.stream

    def spy(messages, model, max_tokens):
        captured.append(messages)
        return orig(messages, model, max_tokens)

    llm.stream = spy
    await s.ask_text("Tell me about the Kubernetes migration.")
    await settle(s)
    await s.ask_text("Why did you choose that?")
    await settle(s)
    roles = [m["role"] for m in captured[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert "follow-up" in captured[1][-1]["content"]
