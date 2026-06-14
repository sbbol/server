"""Гибридный поиск: семантический (Qdrant) + BM25 с RRF-фьюжном."""

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

from app.config import (
    COLLECTION_NAME,
    EMBED_QUERY_PREFIX,
    EMBEDDING_MODEL,
    HYBRID_TOP_K,
    QDRANT_URL,
    RRF_K,
)
from app.search.bm25_index import bm25_store

_embedder: SentenceTransformer | None = None
_qdrant: QdrantClient | None = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def _get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(url=QDRANT_URL)
    return _qdrant


def preload_embedder() -> None:
    """Загружает модель эмбеддингов при старте, чтобы не блокировать первый запрос."""
    _get_embedder()


def _vector_search(query: str, top_k: int) -> list[dict]:
    embedder = _get_embedder()
    qdrant = _get_qdrant()
    query_embedding = embedder.encode(f"{EMBED_QUERY_PREFIX}{query}", normalize_embeddings=True).tolist()

    try:
        result = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_embedding,
            limit=top_k,
        )
    except Exception:
        return []

    hits = []
    for rank, point in enumerate(result.points):
        payload = point.payload or {}
        hits.append({
            "id": str(point.id),
            "text": payload.get("content", ""),
            "source": payload.get("source", ""),
            "title": payload.get("title", ""),
            "chunk_index": payload.get("chunk_index", 0),
            "score": float(point.score) if point.score else 0.0,
            "rank": rank,
        })
    return hits


def _rrf_fusion(vector_hits: list[dict], bm25_hits: list[dict], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    chunks: dict[str, dict] = {}

    for hits in (vector_hits, bm25_hits):
        for item in hits:
            cid = item["id"]
            rrf_score = 1.0 / (RRF_K + item["rank"] + 1)
            scores[cid] = scores.get(cid, 0.0) + rrf_score
            if cid not in chunks:
                chunks[cid] = item

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [{**chunks[cid], "rrf_score": score} for cid, score in ranked]


def hybrid_search(query: str, top_k: int = HYBRID_TOP_K) -> list[dict]:
    vector_hits = _vector_search(query, top_k)
    bm25_hits = bm25_store.search(query, top_k) if bm25_store.is_ready else []

    if vector_hits and bm25_hits:
        return _rrf_fusion(vector_hits, bm25_hits, top_k)
    return vector_hits or bm25_hits


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "Релевантная информация в базе знаний не найдена."
    parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("title", "Документ")
        source = chunk.get("source", "")
        text = chunk.get("text", chunk.get("content", ""))
        parts.append(f"[{i}] {title}\nИсточник: {source}\n{text}")
    return "\n\n---\n\n".join(parts)
