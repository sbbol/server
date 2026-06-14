"""
Индексация базы знаний в Qdrant + BM25.

Перед запуском:
    python scripts/preprocess_docs.py   # опционально, если есть сырые файлы
    python ingest.py
"""

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

CHUNKER = SemanticChunker(
    embedding_model=EMBEDDING_MODEL,
    threshold=0.5,
    chunk_size=1024,
    min_sentences=1,
)

BATCH_SIZE = 32


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
                docs.append({"path": file_path, "title": title, "text": text, "source": source})

    return docs


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
        chunks = CHUNKER.chunk(doc["text"])
        print(f"  {doc['title']}: {len(chunks)} чанков")
        for idx, chunk in enumerate(chunks):
            all_chunks.append({
                "id": uuid.uuid4().hex,
                "text": chunk.text,
                "source": doc["source"],
                "title": doc["title"],
                "chunk_index": idx,
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
                },
            )
            for j, chunk in enumerate(batch)
        ]
        CLIENT.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"  Qdrant: {min(i + BATCH_SIZE, len(all_chunks))}/{len(all_chunks)}")

    bm25_store.build(all_chunks)
    print(f"  BM25: индекс сохранён")

    count = CLIENT.count(collection_name=COLLECTION_NAME).count
    print(f"\n✓ Готово. Коллекция '{COLLECTION_NAME}': {count} точек")


if __name__ == "__main__":
    main()
