"""Единая точка маршрутизации сообщений до classify/tools/FAQ."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.intent.classifier import classify
from app.intent.escalation import assess_aggression, is_operator_transfer_request
from app.intent.models import ResponseMode
from app.intent.text_utils import is_faq_question, is_user_data_question
from app.services.conversation_slots import ConversationSlots, is_cancel_message, is_new_topic_message

RouteMode = Literal["TOOL", "FAQ", "ESCALATE", "CLARIFY", "RESET_SLOTS", "AGGRESSION"]

CONFIDENCE_THRESHOLD = 0.85


@dataclass
class RouteDecision:
    mode: RouteMode
    confidence: float
    reason: str
    intents: list = field(default_factory=list)
    reset_slots: bool = False
    aggression_level: int = 0
    aggression_response: str = ""
    increment_aggression_strike: bool = False


def route_message(
    message: str,
    history: list[dict] | None = None,
    slots: ConversationSlots | None = None,
    aggression_strikes: int = 0,
) -> RouteDecision:
    """Определяет режим обработки сообщения (приоритет сверху вниз)."""
    history = history or []
    slots = slots or ConversationSlots()

    if is_operator_transfer_request(message):
        return RouteDecision(
            mode="ESCALATE",
            confidence=1.0,
            reason="Пользователь запросил оператора",
            reset_slots=True,
        )

    aggression = assess_aggression(message, aggression_strikes)
    if aggression.level >= 3:
        return RouteDecision(
            mode="ESCALATE",
            confidence=1.0,
            reason=aggression.reason,
            reset_slots=True,
        )
    if aggression.level == 2:
        return RouteDecision(
            mode="AGGRESSION",
            confidence=1.0,
            reason=aggression.reason,
            reset_slots=True,
            aggression_level=2,
            aggression_response=aggression.response_text,
            increment_aggression_strike=True,
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

    if is_user_data_question(message) or is_faq_question(message):
        if is_user_data_question(message):
            intents = classify(message)
            primary = intents[0] if intents else None
            if primary and primary.response_mode != ResponseMode.FAQ:
                return RouteDecision(
                    mode="TOOL",
                    confidence=primary.score,
                    reason="user_data",
                    intents=intents,
                    aggression_level=aggression.level,
                    aggression_response=aggression.response_text if aggression.level == 1 else "",
                )
        if is_faq_question(message):
            return RouteDecision(
                mode="FAQ",
                confidence=0.9,
                reason="faq_patterns",
                aggression_level=aggression.level,
                aggression_response=aggression.response_text if aggression.level == 1 else "",
            )

    intents = classify(message)
    primary = intents[0]

    if primary.response_mode == ResponseMode.FAQ:
        return RouteDecision(
            mode="FAQ",
            confidence=max(primary.score, 0.5),
            reason="classify_fallback",
            intents=intents,
            aggression_level=aggression.level,
            aggression_response=aggression.response_text if aggression.level == 1 else "",
        )

    if primary.score < CONFIDENCE_THRESHOLD:
        return RouteDecision(
            mode="FAQ",
            confidence=primary.score,
            reason="low_confidence",
            intents=intents,
            aggression_level=aggression.level,
            aggression_response=aggression.response_text if aggression.level == 1 else "",
        )

    return RouteDecision(
        mode="TOOL",
        confidence=primary.score,
        reason="classify_match",
        intents=intents,
        aggression_level=aggression.level,
        aggression_response=aggression.response_text if aggression.level == 1 else "",
    )
