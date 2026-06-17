"""Гибридный поиск: семантический (Qdrant) + BM25 с RRF-фьюжном."""

import logging

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

logger = logging.getLogger(__name__)

_embedder: SentenceTransformer | None = None
_qdrant: QdrantClient | None = None

QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "карт": ("бизнес-карта", "корпоративная карта", "банковская карта"),
    "эцп": ("электронная подпись", "ключ", "носитель", "утеря", "восстановление"),
    "потерял": ("утеря", "поломка"),
    "потеря": ("утеря", "поломка"),
}

DOC_TYPE_BOOST: dict[str, float] = {
    "faq": 3.0,
    "procedure": 1.5,
    "product": 0.3,
}


def expand_query(query: str) -> str:
    normalized = query.lower()
    extras: list[str] = []
    for key, synonyms in QUERY_EXPANSIONS.items():
        if key in normalized:
            extras.extend(synonyms)
    if not extras:
        return query
    return f"{query} {' '.join(extras)}"


def _filter_irrelevant_chunks(query: str, chunks: list[dict]) -> list[dict]:
    """Отсекает чанки про ключи ЭЦП при запросе о банковских картах."""
    normalized = query.lower()
    if "карт" not in normalized:
        return chunks
    if any(t in normalized for t in ("эцп", "подпис", "ключ", "сертификат")):
        return chunks
    filtered = []
    for chunk in chunks:
        text = (chunk.get("text") or chunk.get("content") or "").lower()
        if "карт" in text and "ключ" in text and "эцп" in text:
            continue
        if "карт" in text and "ключ" in text and "носител" in text:
            continue
        filtered.append(chunk)
    return filtered or chunks


def _is_product_only(chunks: list[dict]) -> bool:
    if not chunks:
        return False
    top = chunks[: min(3, len(chunks))]
    return all(c.get("doc_type") == "product" for c in top)


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
    except Exception as exc:
        logger.warning("Qdrant vector search failed: %s", exc)
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
            "doc_type": payload.get("doc_type", "product"),
            "score": float(point.score) if point.score else 0.0,
            "rank": rank,
        })
    return hits


def _rrf_fusion(vector_hits: list[dict], bm25_hits: list[dict], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion с boost по doc_type."""
    scores: dict[str, float] = {}
    chunks: dict[str, dict] = {}

    for hits in (vector_hits, bm25_hits):
        for item in hits:
            cid = item["id"]
            doc_type = item.get("doc_type", "product")
            boost = DOC_TYPE_BOOST.get(doc_type, 1.0)
            rrf_score = boost * (1.0 / (RRF_K + item["rank"] + 1))
            scores[cid] = scores.get(cid, 0.0) + rrf_score
            if cid not in chunks:
                chunks[cid] = item

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [{**chunks[cid], "rrf_score": score} for cid, score in ranked]


def hybrid_search(query: str, top_k: int = HYBRID_TOP_K) -> list[dict]:
    expanded = expand_query(query)
    vector_hits = _vector_search(expanded, top_k)
    bm25_hits: list[dict] = []
    if bm25_store.is_ready:
        bm25_hits = bm25_store.search(expanded, top_k)
    else:
        logger.warning("BM25 index not ready — keyword search skipped")

    if vector_hits and bm25_hits:
        results = _rrf_fusion(vector_hits, bm25_hits, top_k)
    else:
        results = vector_hits or bm25_hits

    if not results:
        logger.warning("Hybrid search returned no results for query: %s", query[:80])
        return []

    results = _filter_irrelevant_chunks(query, results)

    if _is_product_only(results):
        logger.warning(
            "Top chunks are all product type for FAQ query: %s — treating as no knowledge",
            query[:80],
        )
        return []

    return results


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "Релевантная информация в базе знаний не найдена."
    parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("title", "Документ")
        source = chunk.get("source", "")
        doc_type = chunk.get("doc_type", "")
        text = chunk.get("text", chunk.get("content", ""))
        type_label = f" [{doc_type}]" if doc_type else ""
        parts.append(f"[{i}] {title}{type_label}\nИсточник: {source}\n{text}")
    return "\n\n---\n\n".join(parts)
