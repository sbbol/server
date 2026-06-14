"""API Language Adapter — объяснение выделенного текста."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.explain_service import ExplainService

router = APIRouter(prefix="/api", tags=["explain"])


class ExplainRequest(BaseModel):
    text: str


@router.post("/explain")
async def explain_text(request: ExplainRequest):
    service = ExplainService()
    explanation = await service.explain(request.text)
    return {"explanation": explanation}
