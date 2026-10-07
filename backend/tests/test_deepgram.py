"""Call-tab / mic audio path: browser audio -> backend -> Deepgram-style stream -> transcript -> final answer.

Runs against a local fake of Deepgram's live endpoint that speaks the same message protocol."""

import asyncio
import json

from websockets.asyncio.server import serve

from app import stt
from app.session import InterviewSession, SessionConfig
from app.store import ChatStore
from tests.test_session import FakeLLM, of, settle


async def fake_deepgram(ws):
    assert ws.request.headers["Authorization"] == "Token test-key"
    assert "interim_results=true" in ws.request.path
    audio = 0
    async for msg in ws:
        if isinstance(msg, bytes):
            audio += len(msg)
            if audio > 8000:
                continue  # silence after the question
            final = audio == 8000
            words = "Tell me about your Kubernetes work?" if final else "Tell me about"
            await ws.send(json.dumps({"type": "Results", "is_final": final, "speech_final": final,
                                      "channel": {"alternatives": [{"transcript": words}]}}))
        elif json.loads(msg).get("type") == "CloseStream":
            await ws.close()


async def test_audio_stream_produces_transcript_and_final_answer(monkeypatch):
    async with serve(fake_deepgram, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(stt.DeepgramTranscriber, "URL", f"ws://127.0.0.1:{port}/v1/listen")
        monkeypatch.setattr(stt.settings, "deepgram_api_key", "test-key")

        chat = ChatStore().create("tab")
        chat.add_source("cv", "cv.pdf", "Ran Kubernetes clusters for Acme payments.")
        events, errors = [], []

        async def send(m):
            events.append(m)

        async def on_error(msg):
            errors.append(msg)

        session = InterviewSession(chat, FakeLLM(), send, "m", "short", SessionConfig(debounce_s=0.05))
        t = stt.DeepgramTranscriber()
        await t.start(session.on_transcript, on_error)
        for _ in range(3):  # three 4 KB "MediaRecorder" chunks of shared tab audio
            await t.send_audio(b"\x00" * 4000)
            await asyncio.sleep(0.05)
        await settle(session)
        await t.stop()

        assert not errors
        assert of(events, "transcript")[0]["interim"] == "Tell me about"
        end = of(events, "answer_end")[-1]
        assert end["final"] and end["question"] == "Tell me about your Kubernetes work?"
        assert chat.history[-1].question == "Tell me about your Kubernetes work?"
