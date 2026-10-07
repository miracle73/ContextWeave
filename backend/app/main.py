import contextlib
import json

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import ingest
from .agent import LENGTHS
from .config import settings
from .llm import OpenRouterClient
from .session import InterviewSession, SessionConfig
from .store import store
from .stt import make_transcriber

app = FastAPI(title="ContextWeave")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
llm = OpenRouterClient()


def _chat(chat_id: str):
    chat = store.get(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


class NewChat(BaseModel):
    title: str = "Practice interview"


class Sources(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=10)
    repos: list[str] = Field(default_factory=list, max_length=10)


@app.get("/api/config")
def config():
    return {"models": settings.models, "default_model": settings.default_model, "lengths": list(LENGTHS),
            "stt_provider": settings.stt_provider, "llm_configured": bool(settings.openrouter_api_key)}


@app.get("/api/chats")
def list_chats():
    return [{"id": c.id, "title": c.title, "created": c.created} for c in store.chats.values()]


@app.post("/api/chats")
def create_chat(body: NewChat):
    return store.create(body.title).summary()


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    return _chat(chat_id).summary()


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    if not store.delete(chat_id):
        raise HTTPException(404, "Chat not found")
    return {"ok": True}


@app.post("/api/chats/{chat_id}/cv")
async def upload_cv(chat_id: str, file: UploadFile = File(...)):
    chat = _chat(chat_id)
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {settings.max_upload_mb} MB")
    try:
        text = ingest.extract_cv(file.filename or "", data)
    except ingest.IngestError as e:
        raise HTTPException(400, str(e)) from e
    return chat.add_source("cv", file.filename or "cv", text).__dict__


@app.post("/api/chats/{chat_id}/sources")
async def add_sources(chat_id: str, body: Sources):
    chat = _chat(chat_id)
    results = []
    for kind, items, fetch in (("url", body.urls, ingest.fetch_url), ("github", body.repos, ingest.fetch_github)):
        for item in items:
            try:
                name, text = await fetch(item)
                results.append({"input": item, "ok": True, "source": chat.add_source(kind, name, text).__dict__})
            except Exception as e:  # noqa: BLE001
                results.append({"input": item, "ok": False, "error": str(e)[:200]})
    return results


@app.delete("/api/chats/{chat_id}/sources/{source_id}")
def delete_source(chat_id: str, source_id: str):
    if not _chat(chat_id).remove_source(source_id):
        raise HTTPException(404, "Source not found")
    return {"ok": True}


@app.websocket("/ws/{chat_id}")
async def interview_ws(ws: WebSocket, chat_id: str):
    chat = store.get(chat_id)
    await ws.accept()
    if not chat:
        await ws.close(4404, "Chat not found")
        return

    async def send(msg: dict) -> None:
        with contextlib.suppress(Exception):
            await ws.send_json(msg)

    cfg = SessionConfig(debounce_s=settings.debounce_ms / 1000, max_provisional=settings.max_provisional_per_utterance,
                        generations_per_minute=settings.generations_per_minute)
    session = InterviewSession(chat, llm, send, settings.default_model, "medium", cfg)
    transcriber = None

    async def stt_error(message: str) -> None:
        await send({"type": "stt_status", "state": "error", "message": message})

    async def stop_stt() -> None:
        nonlocal transcriber
        if transcriber:
            t, transcriber = transcriber, None
            await t.stop()

    await send({"type": "ready", "stt_provider": settings.stt_provider, "model": session.model,
                "length": session.length, "history": [t.__dict__ for t in chat.history]})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if transcriber:
                    try:
                        await transcriber.send_audio(msg["bytes"])
                    except Exception as e:  # noqa: BLE001
                        await stop_stt()
                        await stt_error(f"Transcription provider error: {e}")
                continue
            try:
                data = json.loads(msg.get("text") or "{}")
            except json.JSONDecodeError:
                continue
            kind = data.get("type")
            if kind == "settings":
                if data.get("model") in settings.models:
                    session.model = data["model"]
                if data.get("length") in LENGTHS:
                    session.length = data["length"]
                await send({"type": "settings", "model": session.model, "length": session.length})
            elif kind == "start_audio":
                await stop_stt()
                try:
                    transcriber = make_transcriber()
                    if transcriber:
                        await transcriber.start(session.on_transcript, stt_error)
                    await send({"type": "stt_status", "state": "listening"})
                except Exception as e:  # noqa: BLE001
                    transcriber = None
                    await stt_error(f"Could not start transcription: {e}")
            elif kind == "stop_audio":
                await stop_stt()
                await session.end_utterance()
                await send({"type": "stt_status", "state": "idle"})
            elif kind == "transcript" and settings.stt_provider == "browser":
                await session.on_transcript(str(data.get("text", "")), bool(data.get("is_final")),
                                            bool(data.get("utterance_end")))
            elif kind == "utterance_end":
                await session.end_utterance()
            elif kind == "ask":
                await session.ask_text(str(data.get("text", "")))
            elif kind == "cancel":
                await session.cancel("user")
            elif kind == "ping":
                await send({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await stop_stt()
        await session.close()
