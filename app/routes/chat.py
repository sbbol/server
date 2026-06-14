"""API-маршруты чата."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.chat_service import ChatService
from app.storage.database import Database

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    user_id: str = "demo_user"
    message: str
    conversation_id: str | None = None


class DraftSuggestionRequest(BaseModel):
    user_id: str = "demo_user"


def create_chat_router(db: Database) -> APIRouter:
    service = ChatService(db)

    @router.post("/chat")
    async def chat(request: ChatRequest):
        dangerous = ["игнорируй", "забудь", "ты теперь", "system:", "prompt:"]
        if any(p in request.message.lower() for p in dangerous):
            async def blocked():
                import json
                yield f'data: {json.dumps({"type": "token", "text": "Некорректный запрос. Уточните вопрос по СберБизнес."}, ensure_ascii=False)}\n\n'
                yield "data: [DONE]\n\n"
            return StreamingResponse(blocked(), media_type="text/event-stream")

        async def event_stream():
            yield ": connected\n\n"
            async for event in service.stream_chat(
                request.user_id,
                request.message,
                request.conversation_id,
            ):
                yield event

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/chat/drafts")
    async def get_drafts(user_id: str = "demo_user"):
        drafts = await service.get_draft_suggestions(user_id)
        return {"drafts": drafts}

    @router.get("/chat/history/{conversation_id}")
    async def get_history(conversation_id: str, user_id: str = "demo_user"):
        conv_messages = db.get_messages(conversation_id)
        return {
            "conversation_id": conversation_id,
            "escalated": db.is_escalated(conversation_id),
            "messages": conv_messages,
        }

    return router
