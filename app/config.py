from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
STORAGE_DIR = BASE_DIR / "storage"
BM25_INDEX_PATH = STORAGE_DIR / "bm25_index.pkl"

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "sber_faq"

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 300.0
OLLAMA_NUM_PREDICT = 256

EMBEDDING_MODEL = "ai-forever/ru-en-RoSBERTa"
EMBED_QUERY_PREFIX = "search_query: "
EMBED_DOC_PREFIX = "search_document: "

HYBRID_TOP_K = 8
RRF_K = 60

DEFAULT_USER_ID = "demo_user"
DB_PATH = STORAGE_DIR / "dale.db"
