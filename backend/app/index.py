"""Per-chat BM25 index. Each chat owns its own ChunkIndex, so retrieval never crosses chats."""

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#]*")
_STOP = set(
    "a an the and or but of to in on for with at by from as is are was were be been it this that these those "
    "i you we they he she me my our your their what which who how why when where do does did can could would "
    "should will have has had about tell describe explain give example please so if not".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size - overlap:]
        if len(buf) + len(p) + 2 > size and buf:
            chunks.append(buf)
            buf = buf[-overlap:] + "\n" + p if overlap else p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf.strip():
        chunks.append(buf)
    return chunks


@dataclass
class Chunk:
    source_id: str
    source_name: str
    text: str
    tf: Counter
    length: int


class ChunkIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []

    def add(self, source_id: str, source_name: str, text: str) -> int:
        n = 0
        for c in chunk_text(text):
            toks = tokenize(c)
            if toks:
                self.chunks.append(Chunk(source_id, source_name, c, Counter(toks), len(toks)))
                n += 1
        return n

    def remove_source(self, source_id: str) -> None:
        self.chunks = [c for c in self.chunks if c.source_id != source_id]

    def search(self, query: str, k: int = 6, k1: float = 1.4, b: float = 0.75) -> list[tuple[float, Chunk]]:
        q = set(tokenize(query))
        if not q or not self.chunks:
            return []
        n = len(self.chunks)
        avg = sum(c.length for c in self.chunks) / n
        df = {t: sum(1 for c in self.chunks if t in c.tf) for t in q}
        scored = []
        for c in self.chunks:
            s = 0.0
            for t in q:
                f = c.tf.get(t, 0)
                if f:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * c.length / avg))
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]
