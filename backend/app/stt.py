"""Replaceable speech-to-text providers.

A provider receives raw audio bytes and calls `on_event(text, is_final, utterance_end)`.
Deepgram live streaming: interim_results gives interim hypotheses, is_final marks a stable segment,
speech_final / UtteranceEnd mark the end of the speaker's utterance.
"""

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from .config import settings

OnEvent = Callable[[str, bool, bool], Awaitable[None]]
OnError = Callable[[str], Awaitable[None]]


class Transcriber(Protocol):
    async def start(self, on_event: OnEvent, on_error: OnError) -> None: ...
    async def send_audio(self, data: bytes) -> None: ...
    async def stop(self) -> None: ...


class DeepgramTranscriber:
    URL = "wss://api.deepgram.com/v1/listen"

    def __init__(self) -> None:
        self.ws = None
        self._tasks: list[asyncio.Task] = []

    async def start(self, on_event: OnEvent, on_error: OnError) -> None:
        params = {"model": settings.deepgram_model, "language": settings.deepgram_language,
                  "interim_results": "true", "smart_format": "true", "punctuate": "true",
                  "endpointing": "400", "utterance_end_ms": "1200", "vad_events": "true"}
        self.ws = await connect(f"{self.URL}?{urlencode(params)}", open_timeout=10,
                                additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"})
        self._tasks = [asyncio.create_task(self._read(on_event, on_error)), asyncio.create_task(self._keepalive())]

    async def _read(self, on_event: OnEvent, on_error: OnError) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "Results":
                    alts = msg.get("channel", {}).get("alternatives") or [{}]
                    text = alts[0].get("transcript", "")
                    is_final = bool(msg.get("is_final"))
                    end = bool(msg.get("speech_final"))
                    if text or end:
                        await on_event(text, is_final, end)
                elif kind == "UtteranceEnd":
                    await on_event("", True, True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await on_error(f"Transcription connection lost: {e}")

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(5)
            with contextlib.suppress(Exception):
                await self.ws.send(json.dumps({"type": "KeepAlive"}))

    async def send_audio(self, data: bytes) -> None:
        if self.ws:
            await self.ws.send(data)

    async def stop(self) -> None:
        if not self.ws:
            return
        with contextlib.suppress(Exception):
            await self.ws.send(json.dumps({"type": "CloseStream"}))
            await asyncio.wait_for(asyncio.shield(self._tasks[0]), 3)
        for t in self._tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await self.ws.close()
        self.ws = None


def make_transcriber() -> Transcriber | None:
    """Returns a server-side transcriber, or None when the browser supplies transcripts."""
    if settings.stt_provider == "deepgram":
        if not settings.deepgram_api_key:
            raise RuntimeError("STT_PROVIDER=deepgram but DEEPGRAM_API_KEY is missing")
        return DeepgramTranscriber()
    return None
