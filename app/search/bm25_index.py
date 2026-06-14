"""BM25-индекс для ключевого поиска по базе знаний."""

import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.config import BM25_INDEX_PATH, STORAGE_DIR


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^\w\sа-яё]", " ", text, flags=re.IGNORECASE)
    return [t for t in text.split() if len(t) > 1]


class BM25Store:
    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._chunks: list[dict] = []

    @property
    def is_ready(self) -> bool:
        return self._bm25 is not None and len(self._chunks) > 0

    def build(self, chunks: list[dict]) -> None:
        """chunks: [{id, text, source, title, chunk_index}]"""
        self._chunks = chunks
        tokenized = [tokenize(c["text"]) for c in chunks]
        self._bm25 = BM25Okapi(tokenized)
        self._save()

    def _save(self) -> None:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(BM25_INDEX_PATH, "wb") as f:
            pickle.dump({"chunks": self._chunks, "bm25": self._bm25}, f)

    def load(self) -> bool:
        if not BM25_INDEX_PATH.exists():
            return False
        with open(BM25_INDEX_PATH, "rb") as f:
            data = pickle.load(f)
        self._chunks = data["chunks"]
        self._bm25 = data["bm25"]
        return True

    def search(self, query: str, top_k: int = 8) -> list[dict]:
        if not self.is_ready:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [
            {**self._chunks[idx], "score": float(score), "rank": rank}
            for rank, (idx, score) in enumerate(ranked)
            if score > 0
        ]


bm25_store = BM25Store()
