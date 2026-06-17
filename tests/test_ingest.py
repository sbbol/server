"""Unit tests for document ingestion."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

for _mod in ("sentence_transformers", "qdrant_client", "chonkie", "rank_bm25"):
    sys.modules.setdefault(_mod, MagicMock())

sys.modules.setdefault("qdrant_client.http", MagicMock())
sys.modules["qdrant_client.http"].models = MagicMock()

import ingest


class IngestTests(unittest.TestCase):
    def test_load_documents_deduplicates_by_title_and_hash(self) -> None:
        with patch.object(ingest, "PROCESSED_DIR", Path("/tmp/processed")), \
             patch.object(ingest.Path, "exists", return_value=True), \
             patch.object(ingest.Path, "rglob") as mock_rglob, \
             patch.object(ingest.Path, "read_text") as mock_read:

            file_a = Path("/tmp/processed/docs/doc.md")
            file_b = Path("/tmp/processed/docs_0925/doc.md")
            mock_rglob.return_value = [file_a, file_b]
            mock_read.return_value = "A" * 200

            docs, stats = ingest.load_documents(faq_only=False)

            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["path"], file_b)
            self.assertGreaterEqual(stats.duplicates, 1)

    def test_faq_only_excludes_import_eksport(self) -> None:
        faq_file = Path("/tmp/processed/faq/cards.md")
        import_file = Path("/tmp/processed/import_eksport_sbbol_ISO/example.md")
        text = "X" * 200

        def rglob_side_effect(pattern: str):
            if pattern == "*.md":
                return [faq_file, import_file]
            return []

        with patch.object(ingest, "PROCESSED_DIR", Path("/tmp/processed")), \
             patch.object(ingest.Path, "exists", return_value=True), \
             patch.object(ingest.Path, "rglob", side_effect=rglob_side_effect), \
             patch.object(ingest.Path, "read_text", return_value=text):

            docs, stats = ingest.load_documents(faq_only=True)

            sources = {doc["source"] for doc in docs}
            self.assertTrue(any("faq" in s for s in sources))
            self.assertFalse(any("import_eksport" in s for s in sources))
            self.assertGreater(stats.excluded, 0)

    def test_chunk_document_handles_long_text(self) -> None:
        stats = ingest.IngestStats()
        long_text = ("Абзац текста для тестирования. " * 500).strip()
        doc = {
            "title": "LongDoc",
            "text": long_text,
            "doc_type": "product",
        }

        with patch.object(ingest, "_semantic_chunk", side_effect=lambda text, *_a, **_k: [text[:400]]):
            chunks = ingest.chunk_document(doc, stats)

        self.assertTrue(chunks)
        self.assertGreater(len(chunks), 1)


if __name__ == "__main__":
    unittest.main()
