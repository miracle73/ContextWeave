"""In-memory chat store. Every chat has its own index, sources and history (no shared state)."""

import time
import uuid
from dataclasses import dataclass, field

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

    def add_source(self, kind: str, name: str, text: str) -> Source:
        sid = uuid.uuid4().hex[:10]
        n = self.index.add(sid, name, text)
        src = Source(sid, kind, name, len(text), n)
        self.sources.append(src)
        return src

    def remove_source(self, sid: str) -> bool:
        before = len(self.sources)
        self.sources = [s for s in self.sources if s.id != sid]
        self.index.remove_source(sid)
        return len(self.sources) != before

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "created": self.created,
                "sources": [s.__dict__ for s in self.sources],
                "history": [t.__dict__ for t in self.history]}


class ChatStore:
    def __init__(self) -> None:
        self.chats: dict[str, Chat] = {}

    def create(self, title: str) -> Chat:
        chat = Chat(uuid.uuid4().hex[:12], title.strip()[:80] or "Practice interview")
        self.chats[chat.id] = chat
        return chat

    def get(self, chat_id: str) -> Chat | None:
        return self.chats.get(chat_id)

    def delete(self, chat_id: str) -> bool:
        return self.chats.pop(chat_id, None) is not None


store = ChatStore()
