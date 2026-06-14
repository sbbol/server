"""
Точка входа сервера Дэйл — AI-помощник СберБизнес.

Запуск: python server.py
API docs: http://localhost:8000/docs
Оператор: http://localhost:8000/operator
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes.chat import create_chat_router
from app.routes.data import create_data_router
from app.routes.drafts import create_drafts_router
from app.routes.explain import router as explain_router
from app.routes.operator import create_operator_router
from app.search.bm25_index import bm25_store
from app.search.hybrid import preload_embedder
from app.storage.database import Database

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bm25_store.load()
    preload_embedder()
    yield


app = FastAPI(
    title="Дэйл — AI-помощник СберБизнес",
    description="Умный FAQ, Deep Linking, Language Adapter, AI-Ревайндер",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database()

app.include_router(create_chat_router(db))
app.include_router(create_data_router(db))
app.include_router(explain_router)
app.include_router(create_drafts_router(db))
app.include_router(create_operator_router(db))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bm25_ready": bm25_store.is_ready,
        "assistant": "Дэйл",
    }


@app.get("/operator")
async def operator_page():
    path = STATIC_DIR / "operator.html"
    if path.exists():
        return FileResponse(path)
    return {"message": "Страница оператора: создайте static/operator.html"}


# Обратная совместимость со старым endpoint
@app.post("/chat")
async def chat_legacy(request_body: dict):
    from app.routes.chat import ChatRequest
    from app.services.chat_service import ChatService
    from fastapi.responses import StreamingResponse

    req = ChatRequest(**request_body)
    service = ChatService(db)

    async def event_stream():
        yield ": connected\n\n"
        async for event in service.stream_chat(req.user_id, req.message, req.conversation_id):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
