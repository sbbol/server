"""Единая точка маршрутизации сообщений до classify/tools/FAQ."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.intent.classifier import classify
from app.intent.escalation import should_escalate_to_operator
from app.intent.models import MatchedIntent, ResponseMode
from app.intent.text_utils import is_faq_question
from app.services.conversation_slots import ConversationSlots, is_cancel_message, is_new_topic_message

RouteMode = Literal["TOOL", "FAQ", "ESCALATE", "CLARIFY", "RESET_SLOTS"]

CONFIDENCE_THRESHOLD = 0.85


@dataclass
class RouteDecision:
    mode: RouteMode
    confidence: float
    reason: str
    intents: list[MatchedIntent] = field(default_factory=list)
    reset_slots: bool = False


def route_message(
    message: str,
    history: list[dict] | None = None,
    slots: ConversationSlots | None = None,
) -> RouteDecision:
    """Определяет режим обработки сообщения (приоритет сверху вниз)."""
    history = history or []
    slots = slots or ConversationSlots()

    escalation_reason = should_escalate_to_operator(message)
    if escalation_reason:
        return RouteDecision(
            mode="ESCALATE",
            confidence=1.0,
            reason=escalation_reason,
            reset_slots=True,
        )

    if is_cancel_message(message):
        return RouteDecision(
            mode="RESET_SLOTS",
            confidence=1.0,
            reason="cancel_message",
            reset_slots=True,
        )

    topic_shift = bool(slots.active_intent and is_new_topic_message(message, slots))
    if topic_shift:
        if is_faq_question(message):
            return RouteDecision(
                mode="FAQ",
                confidence=0.95,
                reason="topic_shift_faq",
                reset_slots=True,
            )
        intents = classify(message)
        return RouteDecision(
            mode="TOOL",
            confidence=intents[0].score if intents else 0.0,
            reason="topic_shift",
            intents=intents,
            reset_slots=True,
        )

    if is_faq_question(message):
        return RouteDecision(
            mode="FAQ",
            confidence=0.9,
            reason="faq_patterns",
        )

    intents = classify(message)
    primary = intents[0]

    if primary.response_mode == ResponseMode.FAQ:
        return RouteDecision(
            mode="FAQ",
            confidence=max(primary.score, 0.5),
            reason="classify_fallback",
            intents=intents,
        )

    if primary.score < CONFIDENCE_THRESHOLD:
        return RouteDecision(
            mode="FAQ",
            confidence=primary.score,
            reason="low_confidence",
            intents=intents,
        )

    return RouteDecision(
        mode="TOOL",
        confidence=primary.score,
        reason="classify_match",
        intents=intents,
    )
