"""In-memory chat store. Every chat has its own index, sources and history (no shared state)."""

import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from .config import settings

from .index import ChunkIndex


@dataclass
class Turn:
    question: str
    answer: str
    ts: float = field(default_factory=time.time)


@dataclass
class Source:
    id: str
    kind: str  # cv | url | github
    name: str
    chars: int
    chunks: int


@dataclass
class Chat:
    id: str
    title: str
    created: float = field(default_factory=time.time)
    index: ChunkIndex = field(default_factory=ChunkIndex)
    sources: list[Source] = field(default_factory=list)
    history: list[Turn] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict, repr=False)
    persist: Callable[["Chat"], None] | None = field(default=None, repr=False, compare=False)

    def save(self) -> None:
        if self.persist:
            self.persist(self)

    def add_source(self, kind: str, name: str, text: str, sid: str | None = None, save: bool = True) -> Source:
        sid = sid or uuid.uuid4().hex[:10]
        n = self.index.add(sid, name, text)
        src = Source(sid, kind, name, len(text), n)
        self.sources.append(src)
        self.texts[sid] = text
        if save:
            self.save()
        return src

    def remove_source(self, sid: str) -> bool:
        before = len(self.sources)
        self.sources = [s for s in self.sources if s.id != sid]
        self.index.remove_source(sid)
        self.texts.pop(sid, None)
        self.save()
        return len(self.sources) != before

    def to_record(self) -> dict:
        return {"id": self.id, "title": self.title, "created": self.created,
                "sources": [{"id": s.id, "kind": s.kind, "name": s.name, "text": self.texts.get(s.id, "")}
                            for s in self.sources],
                "history": [t.__dict__ for t in self.history]}

    @classmethod
    def from_record(cls, r: dict) -> "Chat":
        chat = cls(r["id"], r["title"], r["created"], history=[Turn(**t) for t in r["history"]])
        for s in r["sources"]:
            chat.add_source(s["kind"], s["name"], s["text"], sid=s["id"], save=False)
        return chat

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "created": self.created,
                "sources": [s.__dict__ for s in self.sources],
                "history": [t.__dict__ for t in self.history]}


class Database:
    """Stores each chat as one JSON record. Postgres (postgres://...) or SQLite (sqlite:///path)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.pg = url.startswith(("postgres://", "postgresql://"))
        self.ph = "%s" if self.pg else "?"
        self._connect()
        self._exec("CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    def _connect(self) -> None:
        if self.pg:
            import psycopg

            self.conn = psycopg.connect(self.url, autocommit=True)
        else:
            self.conn = sqlite3.connect(self.url.removeprefix("sqlite:///"), check_same_thread=False,
                                        isolation_level=None)

    def _exec(self, sql: str, params: tuple = ()):
        # Neon closes idle connections (scale-to-zero); reconnect once and retry.
        try:
            return self.conn.execute(sql, params)
        except Exception:  # noqa: BLE001
            if not self.pg:
                raise
            self._connect()
            return self.conn.execute(sql, params)

    def load(self) -> list[dict]:
        return [json.loads(row[0]) for row in self._exec("SELECT data FROM chats").fetchall()]

    def save(self, chat: Chat) -> None:
        self._exec(f"INSERT INTO chats (id, data) VALUES ({self.ph}, {self.ph}) "
                   "ON CONFLICT (id) DO UPDATE SET data = excluded.data",
                   (chat.id, json.dumps(chat.to_record())))

    def delete(self, chat_id: str) -> None:
        self._exec(f"DELETE FROM chats WHERE id = {self.ph}", (chat_id,))


class ChatStore:
    def __init__(self, db: Database | None = None) -> None:
        self.chats: dict[str, Chat] = {}
        self.db = db
        if db:
            for r in db.load():
                chat = Chat.from_record(r)
                chat.persist = db.save
                self.chats[chat.id] = chat

    def create(self, title: str) -> Chat:
        chat = Chat(uuid.uuid4().hex[:12], title.strip()[:80] or "Practice interview")
        self.chats[chat.id] = chat
        if self.db:
            chat.persist = self.db.save
            chat.save()
        return chat

    def get(self, chat_id: str) -> Chat | None:
        return self.chats.get(chat_id)

    def delete(self, chat_id: str) -> bool:
        if self.db and chat_id in self.chats:
            self.db.delete(chat_id)
        return self.chats.pop(chat_id, None) is not None


store = ChatStore(Database(settings.database_url) if settings.database_url else None)
