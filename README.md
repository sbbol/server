# Дейл — backend ассистента СберБизнес

FastAPI-сервер AI-помощника «Дейл»: чат (SSE), RAG по базе знаний, intent-роутинг, автозаполнение форм, черновики, эскалация к оператору.

Связанные репозитории: веб-клиент (`sbolb_assistant_web`), мобильное приложение (`sbolb_assistant_mobile`).

## Требования

- Python 3.11+
- [Ollama](https://ollama.com/) с моделью `qwen2.5:7b` (или значение из `OLLAMA_MODEL`)
- [Qdrant](https://qdrant.tech/) на `localhost:6333`

## Первый запуск

```bash
cd server
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# Индексация базы знаний (Qdrant + BM25)
python ingest.py

# Запуск API
python server.py
```

После запуска:

- Swagger UI: http://localhost:8000/docs
- Панель оператора: http://localhost:8000/operator

Без `ingest.py` FAQ-ответы будут без контекста документов — в чате появится статус «База знаний недоступна».

## База знаний и артефакты

| Путь | Описание |
|------|----------|
| `data/` | Исходные документы (PDF, DOC) и обработанные markdown-файлы для RAG |
| `storage/dale.db` | SQLite: история чатов, черновики, демо-данные (создаётся при первом запуске) |
| `storage/bm25_index.pkl` | Локальный BM25-индекс (генерируется `ingest.py`) |

## Основные эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/chat` | SSE-стрим чата |
| GET | `/api/chat/history/{id}` | История диалога |
| GET/POST/DELETE | `/api/drafts` | Черновики форм |
| POST | `/api/explain` | Объяснение выделенного текста |
| GET/POST | `/api/operator/*` | Панель оператора |
| GET | `/operator.html` | UI оператора (демо) |
| GET | `/api/data/*` | Демо-данные: счета, сотрудники, карты, выписки |

## Конфигурация

Настройки по умолчанию — в `app/config.py`:

| Параметр | Значение по умолчанию |
|----------|----------------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen2.5:7b` |
| `QDRANT_URL` | `http://localhost:6333` |
| `EMBEDDING_MODEL` | `ai-forever/ru-en-RoSBERTa` |

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Примечание

Проект использует брендинг и документацию СберБизнес в демонстрационных целях.
