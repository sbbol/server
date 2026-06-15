"""
Индексация базы знаний в Qdrant + BM25.

Перед запуском:
    python scripts/preprocess_docs.py   # опционально, если есть сырые файлы
    python ingest.py
"""

import re
import uuid
from pathlib import Path

from chonkie import SemanticChunker
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

from app.config import (
    COLLECTION_NAME,
    DATA_DIR,
    EMBED_DOC_PREFIX,
    EMBEDDING_MODEL,
    PROCESSED_DIR,
    QDRANT_URL,
)
from app.search.bm25_index import bm25_store

EMBEDDER = SentenceTransformer(EMBEDDING_MODEL)
VECTOR_DIM = EMBEDDER.get_embedding_dimension()
CLIENT = QdrantClient(url=QDRANT_URL)

FAQ_CHUNKER = SemanticChunker(
    embedding_model=EMBEDDING_MODEL,
    threshold=0.5,
    chunk_size=400,
    min_sentences=1,
)

DEFAULT_CHUNKER = SemanticChunker(
    embedding_model=EMBEDDING_MODEL,
    threshold=0.5,
    chunk_size=1024,
    min_sentences=1,
)

BATCH_SIZE = 32

QA_PATTERN = re.compile(
    r"##\s*Вопрос:\s*(.+?)\s*\n+\*\*Ответ:\*\*\s*(.+?)(?=\n##|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def load_documents() -> list[dict]:
    """Загружает .md из processed/, иначе .txt/.xml из data/."""
    docs = []
    search_dirs = []

    if PROCESSED_DIR.exists() and any(PROCESSED_DIR.rglob("*.md")):
        search_dirs.append(PROCESSED_DIR)
        patterns = ["*.md"]
    else:
        search_dirs.append(DATA_DIR)
        patterns = ["*.txt", "*.xml", "*.md"]

    for base in search_dirs:
        for pattern in patterns:
            for file_path in sorted(base.rglob(pattern)):
                if "processed" in file_path.parts and base == DATA_DIR:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="replace")
                title = file_path.stem.strip()
                source = str(file_path.relative_to(base))
                doc_type = _detect_doc_type(file_path, text)
                docs.append({
                    "path": file_path,
                    "title": title,
                    "text": text,
                    "source": source,
                    "doc_type": doc_type,
                })

    return docs


def _detect_doc_type(file_path: Path, text: str) -> str:
    rel = str(file_path).lower()
    if "/faq/" in rel.replace("\\", "/") or rel.endswith("faq"):
        return "faq"
    if "инструк" in text.lower()[:500] or "порядок" in text.lower()[:500]:
        return "procedure"
    return "product"


def _extract_keywords(text: str, title: str) -> list[str]:
    keywords: set[str] = {title.lower()}
    kw_match = re.search(r"##\s*Ключевые слова\s*\n(.+)", text, re.I)
    if kw_match:
        for part in re.split(r"[,;\n]", kw_match.group(1)):
            word = part.strip().lower()
            if word:
                keywords.add(word)
    for token in re.findall(r"[а-яa-z]{4,}", title.lower()):
        keywords.add(token)
    return sorted(keywords)[:20]


def _faq_qa_chunks(text: str) -> list[str]:
    """Разбивает FAQ-документ на пары «Вопрос / Ответ»."""
    pairs = QA_PATTERN.findall(text)
    if pairs:
        return [f"Вопрос: {q.strip()}\nОтвет: {a.strip()}" for q, a in pairs]
    return []


def chunk_document(doc: dict) -> list[str]:
    doc_type = doc["doc_type"]
    if doc_type == "faq":
        qa_chunks = _faq_qa_chunks(doc["text"])
        if qa_chunks:
            return qa_chunks
        return [c.text for c in FAQ_CHUNKER.chunk(doc["text"])]
    return [c.text for c in DEFAULT_CHUNKER.chunk(doc["text"])]


def recreate_collection() -> None:
    if CLIENT.collection_exists(COLLECTION_NAME):
        CLIENT.delete_collection(COLLECTION_NAME)
    CLIENT.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=VECTOR_DIM, distance=models.Distance.COSINE),
    )


def main() -> None:
    print("=== Индексация базы знаний СберБизнес ===\n")

    raw_docs = load_documents()
    if not raw_docs:
        print("Документы не найдены. Запустите: python scripts/preprocess_docs.py")
        return

    print(f"Найдено документов: {len(raw_docs)}")

    all_chunks: list[dict] = []
    for doc in raw_docs:
        chunks = chunk_document(doc)
        keywords = _extract_keywords(doc["text"], doc["title"])
        print(f"  {doc['title']} ({doc['doc_type']}): {len(chunks)} чанков")
        for idx, chunk_text in enumerate(chunks):
            all_chunks.append({
                "id": uuid.uuid4().hex,
                "text": chunk_text,
                "source": doc["source"],
                "title": doc["title"],
                "chunk_index": idx,
                "doc_type": doc["doc_type"],
                "keywords": keywords,
            })

    print(f"\nВсего чанков: {len(all_chunks)}")
    recreate_collection()

    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        texts = [f"{EMBED_DOC_PREFIX}{c['text']}" for c in batch]
        embeddings = EMBEDDER.encode(texts, normalize_embeddings=True, show_progress_bar=False)

        points = [
            models.PointStruct(
                id=chunk["id"],
                vector=embeddings[j].tolist(),
                payload={
                    "content": chunk["text"],
                    "source": chunk["source"],
                    "title": chunk["title"],
                    "chunk_index": chunk["chunk_index"],
                    "doc_type": chunk["doc_type"],
                    "keywords": chunk["keywords"],
                },
            )
            for j, chunk in enumerate(batch)
        ]
        CLIENT.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"  Qdrant: {min(i + BATCH_SIZE, len(all_chunks))}/{len(all_chunks)}")

    bm25_store.build(all_chunks)
    print("  BM25: индекс сохранён")

    count = CLIENT.count(collection_name=COLLECTION_NAME).count
    print(f"\n✓ Готово. Коллекция '{COLLECTION_NAME}': {count} точек")


if __name__ == "__main__":
    main()
