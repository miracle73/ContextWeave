import contextlib
import json
import uuid

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


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"models": settings.models, "default_model": settings.default_model, "lengths": list(LENGTHS),
            "stt_provider": settings.stt_provider, "llm_configured": bool(settings.openrouter_api_key)}


@app.get("/api/chats")
def list_chats():
    return [{"id": c.id, "title": c.title, "created": c.created} for c in store.chats.values()]


@app.post("/api/chats")
async def create_chat(body: NewChat):
    chat = store.create(body.title)
    await lobby_broadcast({"type": "chats_changed"})
    return chat.summary()


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    return _chat(chat_id).summary()


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    if not store.delete(chat_id):
        raise HTTPException(404, "Chat not found")
    await lobby_broadcast({"type": "chats_changed"})
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
    src = chat.add_source("cv", file.filename or "cv", text)
    await room_broadcast(chat_id, {"type": "sources_changed"})
    return src.__dict__


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
    await room_broadcast(chat_id, {"type": "sources_changed"})
    return results


@app.delete("/api/chats/{chat_id}/sources/{source_id}")
async def delete_source(chat_id: str, source_id: str):
    if not _chat(chat_id).remove_source(source_id):
        raise HTTPException(404, "Source not found")
    await room_broadcast(chat_id, {"type": "sources_changed"})
    return {"ok": True}


# ---- real-time sync: one shared live session per chat, mirrored to every open device ----

async def _safe_send(ws: WebSocket, msg: dict) -> None:
    with contextlib.suppress(Exception):
        await ws.send_json(msg)


class Room:
    def __init__(self, chat) -> None:
        self.chat = chat
        self.clients: dict[str, WebSocket] = {}
        self.mic_owner: str | None = None
        self.transcriber = None
        cfg = SessionConfig(debounce_s=settings.debounce_ms / 1000,
                            max_provisional=settings.max_provisional_per_utterance,
                            generations_per_minute=settings.generations_per_minute)
        self.session = InterviewSession(chat, llm, self.broadcast, settings.default_model, "medium", cfg)

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self.clients.values()):
            await _safe_send(ws, msg)

    async def send_to(self, cid: str | None, msg: dict) -> None:
        if cid in self.clients:
            await _safe_send(self.clients[cid], msg)

    async def release_mic(self) -> None:
        t, self.transcriber = self.transcriber, None
        if t:
            await t.stop()
        if self.mic_owner:
            self.mic_owner = None
            await self.session.end_utterance()
            await self.broadcast({"type": "mic", "owner": None})


rooms: dict[str, Room] = {}
lobby: set[WebSocket] = set()


async def room_broadcast(chat_id: str, msg: dict) -> None:
    if chat_id in rooms:
        await rooms[chat_id].broadcast(msg)


async def lobby_broadcast(msg: dict) -> None:
    for ws in list(lobby):
        await _safe_send(ws, msg)


@app.websocket("/ws/lobby")
async def lobby_ws(ws: WebSocket):
    await ws.accept()
    lobby.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        lobby.discard(ws)


@app.websocket("/ws/{chat_id}")
async def interview_ws(ws: WebSocket, chat_id: str):
    chat = store.get(chat_id)
    await ws.accept()
    if not chat:
        await ws.close(4404, "Chat not found")
        return
    room = rooms.get(chat_id) or rooms.setdefault(chat_id, Room(chat))
    cid = uuid.uuid4().hex[:8]
    room.clients[cid] = ws
    session = room.session

    async def stt_error(message: str) -> None:
        await room.send_to(room.mic_owner, {"type": "stt_status", "state": "error", "message": message})
        await room.release_mic()

    await _safe_send(ws, {"type": "ready", "client_id": cid, "stt_provider": settings.stt_provider,
                          "mic_owner": room.mic_owner, "history": [t.__dict__ for t in chat.history],
                          **session.snapshot()})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if room.transcriber and room.mic_owner == cid:
                    try:
                        await room.transcriber.send_audio(msg["bytes"])
                    except Exception as e:  # noqa: BLE001
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
                await room.broadcast({"type": "settings", "model": session.model, "length": session.length})
            elif kind == "start_audio":
                if room.mic_owner and room.mic_owner != cid:
                    await _safe_send(ws, {"type": "stt_status", "state": "error",
                                          "message": "The mic is already live on another device. Stop it there first."})
                    continue
                await room.release_mic()
                room.mic_owner = cid
                await room.broadcast({"type": "mic", "owner": cid})
                try:
                    room.transcriber = make_transcriber()
                    if room.transcriber:
                        await room.transcriber.start(session.on_transcript, stt_error)
                    await _safe_send(ws, {"type": "stt_status", "state": "listening"})
                except Exception as e:  # noqa: BLE001
                    room.transcriber = None
                    await stt_error(f"Could not start transcription: {e}")
            elif kind == "stop_audio":
                if room.mic_owner == cid:
                    await room.release_mic()
                await _safe_send(ws, {"type": "stt_status", "state": "idle"})
            elif kind == "transcript" and settings.stt_provider == "browser" and room.mic_owner == cid:
                await session.on_transcript(str(data.get("text", "")), bool(data.get("is_final")),
                                            bool(data.get("utterance_end")))
            elif kind == "utterance_end" and room.mic_owner == cid:
                await session.end_utterance()
            elif kind == "ask":
                await session.ask_text(str(data.get("text", "")))
            elif kind == "cancel":
                await session.cancel("user")
            elif kind == "ping":
                await _safe_send(ws, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        room.clients.pop(cid, None)
        if room.mic_owner == cid:
            await room.release_mic()
        if not room.clients:  # last device left
            rooms.pop(chat_id, None)
            await session.close()
