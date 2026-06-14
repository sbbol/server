"""API для клиента сотрудника банка (эскалация)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.storage.database import Database

router = APIRouter(prefix="/api/operator", tags=["operator"])


class OperatorReply(BaseModel):
    conversation_id: str
    content: str


def create_operator_router(db: Database) -> APIRouter:
    @router.get("/conversations")
    async def list_escalated():
        conversations = db.get_escalated_conversations()
        result = []
        for conv in conversations:
            messages = db.get_messages(conv["id"])
            result.append({**conv, "messages": messages})
        return {"conversations": result}

    @router.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str):
        messages = db.get_messages(conversation_id)
        return {"conversation_id": conversation_id, "messages": messages}

    @router.post("/reply")
    async def operator_reply(request: OperatorReply):
        db.add_message(request.conversation_id, "operator", request.content)
        return {"status": "ok"}

    return router
