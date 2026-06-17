"""
Индексация базы знаний в Qdrant + BM25.

Перед запуском:
    python scripts/preprocess_docs.py   # опционально, если есть сырые файлы
    python ingest.py                  # faq-only (по умолчанию)
    python ingest.py --all            # все документы кроме import-примеров
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import uuid
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
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

logger = logging.getLogger(__name__)

MAX_DOC_CHARS = 50_000
MAX_PRE_CHUNK_CHARS = 2000
MIN_DOC_CHARS = 100

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
    chunk_size=400,
    min_sentences=1,
)

BATCH_SIZE = 32

QA_PATTERN = re.compile(
    r"##\s*Вопрос:\s*(.+?)\s*\n+\*\*Ответ:\*\*\s*(.+?)(?=\n##|\Z)",
    re.DOTALL | re.IGNORECASE,
)

EXCLUDE_PATH_PATTERNS = (
    "import_eksport",
    "пример формата",
    "выписки xml",
    "paydoc",
)

EXCLUDE_FILENAME_PREFIXES = (
    "пп_",
    "пт_iso_",
    "список_на_выплату",
)


@dataclass
class IngestStats:
    faq_docs: int = 0
    faq_chunks: int = 0
    procedure_docs: int = 0
    procedure_chunks: int = 0
    product_docs: int = 0
    product_chunks: int = 0
    excluded: int = 0
    excluded_reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    warnings: list[str] = field(default_factory=list)
    duplicates: int = 0
    skipped_huge: int = 0
    skipped_tiny: int = 0


def _content_hash(text: str) -> str:
    return hashlib.md5(text[:500].encode("utf-8")).hexdigest()


def _path_preference(path: Path) -> int:
    rel = str(path).lower().replace("\\", "/")
    score = 0
    if "_0925" in rel:
        score += 10
    if "import_eksport" in rel and "_0925" not in rel:
        score -= 5
    return score


def _detect_doc_type(file_path: Path, text: str) -> str:
    rel = str(file_path).lower().replace("\\", "/")
    if "/faq/" in rel or rel.endswith("/faq"):
        return "faq"
    if "инструк" in text.lower()[:500] or "порядок" in text.lower()[:500]:
        return "procedure"
    return "product"


def _should_include_path(file_path: Path, text: str, faq_only: bool) -> tuple[bool, str]:
    rel = str(file_path).lower().replace("\\", "/")
    stem = file_path.stem.lower()

    for prefix in EXCLUDE_FILENAME_PREFIXES:
        if stem.startswith(prefix):
            return False, f"prefix:{prefix}"

    for pat in EXCLUDE_PATH_PATTERNS:
        if pat in rel:
            return False, f"path:{pat}"

    if not faq_only:
        return True, ""

    if "/faq/" in rel:
        return True, ""
    if "/доп/" in rel:
        return True, ""

    head = text.lower()[:500]
    if "порядок" in head or "инструк" in head:
        return True, ""

    return False, "faq_only_filter"


def load_documents(faq_only: bool = True) -> tuple[list[dict], IngestStats]:
    """Загружает .md из processed/, иначе .txt/.xml из data/."""
    stats = IngestStats()
    docs: list[dict] = []
    search_dirs: list[Path] = []

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

                try:
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    stats.warnings.append(f"Не удалось прочитать {file_path}: {exc}")
                    continue

                if len(text) > MAX_DOC_CHARS:
                    stats.skipped_huge += 1
                    stats.warnings.append(
                        f"Пропущен гигантский файл ({len(text)} символов): {file_path.name}",
                    )
                    continue

                if len(text.strip()) < MIN_DOC_CHARS:
                    stats.skipped_tiny += 1
                    stats.warnings.append(
                        f"Пропущен короткий файл ({len(text.strip())} символов): {file_path.name}",
                    )
                    continue

                include, reason = _should_include_path(file_path, text, faq_only)
                if not include:
                    stats.excluded += 1
                    stats.excluded_reasons[reason] += 1
                    continue

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

    deduped: dict[tuple[str, str], tuple[dict, int]] = {}
    for doc in docs:
        key = (doc["title"], _content_hash(doc["text"]))
        pref = _path_preference(doc["path"])
        if key not in deduped or pref > deduped[key][1]:
            if key in deduped:
                stats.duplicates += 1
            deduped[key] = (doc, pref)

    final_docs = [item[0] for item in deduped.values()]
    stats.excluded += stats.duplicates
    if stats.duplicates:
        stats.excluded_reasons["duplicate"] = stats.duplicates

    return final_docs, stats


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


def _pre_split_text(text: str, max_chars: int = MAX_PRE_CHUNK_CHARS) -> list[str]:
    """Режет длинный текст на части до semantic chunking."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                for i in range(0, len(para), max_chars):
                    chunks.append(para[i : i + max_chars])
                current = ""

    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def _semantic_chunk(text: str, chunker: SemanticChunker, stats: IngestStats, label: str) -> list[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return [c.text for c in chunker.chunk(text)]
        except Exception as exc:
            stats.warnings.append(f"Semantic chunk fallback для {label}: {exc}")
            return _pre_split_text(text, MAX_PRE_CHUNK_CHARS)


def chunk_document(doc: dict, stats: IngestStats) -> list[str]:
    doc_type = doc["doc_type"]
    if doc_type == "faq":
        qa_chunks = _faq_qa_chunks(doc["text"])
        if qa_chunks:
            return qa_chunks
        if len(doc["text"]) <= MAX_PRE_CHUNK_CHARS:
            return _semantic_chunk(doc["text"], FAQ_CHUNKER, stats, doc["title"])
        parts: list[str] = []
        for piece in _pre_split_text(doc["text"]):
            parts.extend(_semantic_chunk(piece, FAQ_CHUNKER, stats, doc["title"]))
        return parts

    parts: list[str] = []
    for piece in _pre_split_text(doc["text"]):
        parts.extend(_semantic_chunk(piece, DEFAULT_CHUNKER, stats, doc["title"]))
    return parts


def recreate_collection() -> None:
    if CLIENT.collection_exists(COLLECTION_NAME):
        CLIENT.delete_collection(COLLECTION_NAME)
    CLIENT.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=VECTOR_DIM, distance=models.Distance.COSINE),
    )


def _print_stats(stats: IngestStats) -> None:
    print("\n=== Статистика индексации ===")
    print(f"FAQ: {stats.faq_docs} docs, {stats.faq_chunks} chunks")
    print(f"Procedure: {stats.procedure_docs} docs, {stats.procedure_chunks} chunks")
    print(f"Product: {stats.product_docs} docs, {stats.product_chunks} chunks")
    print(f"Excluded: {stats.excluded} files (duplicates, import examples, filters)")
    if stats.skipped_huge:
        print(f"  Skipped huge: {stats.skipped_huge}")
    if stats.skipped_tiny:
        print(f"  Skipped tiny: {stats.skipped_tiny}")
    if stats.warnings:
        print(f"Warnings ({len(stats.warnings)}):")
        for w in stats.warnings[:15]:
            print(f"  - {w}")
        if len(stats.warnings) > 15:
            print(f"  ... и ещё {len(stats.warnings) - 15}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Индексация базы знаний СберБизнес")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Индексировать все документы (не только FAQ/procedure)",
    )
    args = parser.parse_args()
    faq_only = not args.all

    print("=== Индексация базы знаний СберБизнес ===")
    print(f"Режим: {'faq-only' if faq_only else 'all (без import-примеров)'}\n")

    raw_docs, stats = load_documents(faq_only=faq_only)
    if not raw_docs:
        print("Документы не найдены. Запустите: python scripts/preprocess_docs.py")
        _print_stats(stats)
        return

    print(f"Найдено документов: {len(raw_docs)}")

    all_chunks: list[dict] = []
    titles_seen: set[str] = set()
    for doc in raw_docs:
        if doc["title"] in titles_seen:
            stats.warnings.append(f"Дубликат title в индексе: {doc['title']}")
        titles_seen.add(doc["title"])

        chunks = chunk_document(doc, stats)
        keywords = _extract_keywords(doc["text"], doc["title"])
        doc_type = doc["doc_type"]

        if doc_type == "faq":
            stats.faq_docs += 1
            stats.faq_chunks += len(chunks)
        elif doc_type == "procedure":
            stats.procedure_docs += 1
            stats.procedure_chunks += len(chunks)
        else:
            stats.product_docs += 1
            stats.product_chunks += len(chunks)

        print(f"  {doc['title']} ({doc_type}): {len(chunks)} чанков")
        for idx, chunk_text in enumerate(chunks):
            all_chunks.append({
                "id": uuid.uuid4().hex,
                "text": chunk_text,
                "source": doc["source"],
                "title": doc["title"],
                "chunk_index": idx,
                "doc_type": doc_type,
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
    _print_stats(stats)


if __name__ == "__main__":
    main()
