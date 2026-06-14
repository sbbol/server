"""API черновиков (AI-Ревайндер)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.storage.database import Database

router = APIRouter(prefix="/api", tags=["drafts"])


class DraftRequest(BaseModel):
    user_id: str = "demo_user"
    draft_type: str
    title: str
    route: str
    form_data: dict = {}
    draft_id: str | None = None


def create_drafts_router(db: Database) -> APIRouter:
    @router.post("/drafts")
    async def save_draft(request: DraftRequest):
        draft_id = db.upsert_draft(
            request.user_id,
            request.draft_type,
            request.title,
            request.route,
            request.form_data,
            request.draft_id,
        )
        return {"draft_id": draft_id}

    @router.get("/drafts")
    async def list_drafts(user_id: str = "demo_user"):
        return {"drafts": db.get_drafts(user_id)}

    @router.delete("/drafts/{draft_id}")
    async def remove_draft(draft_id: str, user_id: str = "demo_user"):
        deleted = db.delete_draft(user_id, draft_id)
        return {"deleted": deleted}

    return router
