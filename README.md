# Дэйл — backend ассистента СберБизнес

FastAPI-сервер для AI-помощника: чат (SSE), RAG, intent-роутинг, черновики, эскалация к оператору.

## Требования

- Python 3.11+
- [Ollama](https://ollama.com/) с моделью `qwen2.5:7b` (или значение из `OLLAMA_MODEL`)
- [Qdrant](https://qdrant.tech/) на `localhost:6333`

## Первый запуск

```bash
cd server
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Обязательно: индексация базы знаний (Qdrant + BM25)
python ingest.py

# Запуск API
python server.py
```

Без `ingest.py` FAQ-ответы будут без контекста документов — в чате появится статус «База знаний недоступна».

## Основные эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/chat` | SSE-стрим чата |
| GET | `/api/chat/history/{id}` | История диалога |
| GET/POST/DELETE | `/api/drafts` | Черновики форм |
| POST | `/api/explain` | Объяснение выделенного текста |
| GET/POST | `/api/operator/*` | Панель оператора |
| GET | `/operator.html` | UI оператора (демо) |

## Переменные окружения

См. `app/config.py`: `OLLAMA_BASE_URL`, `QDRANT_URL`, `EMBEDDING_MODEL`.
