"""Накопление контекста диалога (слоты) между сообщениями."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.intent.form_hints import extract_form_hints, extract_payment_hints, merge_hints
from app.intent.text_utils import account_matches, normalize


INTENT_SCREENS: dict[str, str] = {
    "payment_create": "instant_payment",
    "payment_order": "payment_order",
    "statements_filter": "statement",
    "requisites": "account_requisites",
    "account_view": "account_view",
    "employees": "employees",
    "service_package": "service_package_form",
    "card_block": "card_management",
}


@dataclass
class ConversationSlots:
    active_intent: str | None = None
    target_screen: str | None = None
    form_data: dict[str, str] = field(default_factory=dict)
    pending_account: bool = False
    last_card_intent: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ConversationSlots:
        if not data:
            return cls()
        return cls(
            active_intent=data.get("active_intent"),
            target_screen=data.get("target_screen"),
            form_data=dict(data.get("form_data") or {}),
            pending_account=bool(data.get("pending_account")),
            last_card_intent=data.get("last_card_intent"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CANCEL_PHRASES = (
    "нет", "не надо", "не нужно", "не хочу", "хватит", "забудь",
    "отмен", "стоп", "не буду", "передумал",
)

_NEW_TOPIC_WORDS = (
    "сотрудник", "работник", "пользовател", "человек", "команд", "карт", "заблок", "разблок",
    "реквизит", "выписк", "тариф", "пакет услуг", "баланс", "остаток",
    "перевод", "платеж", "платёж", "поручен", "мгновен",
)


def is_cancel_message(message: str) -> bool:
    text = normalize(message)
    if len(text) > 120:
        return False
    if text in _CANCEL_PHRASES:
        return True
    return any(p in text for p in _CANCEL_PHRASES if len(p) > 3)


def is_new_topic_message(message: str, slots: ConversationSlots | None = None) -> bool:
    text = normalize(message)
    if slots and slots.active_intent in ("payment_create", "payment_order"):
        if any(w in text for w in ("назначен", "получател", "сумм", "руб", "контрагент", "перевод")):
            return False
    if slots and slots.active_intent == "statements_filter":
        if any(w in text for w in ("выписк", "период", "вчера", "месяц", "счет", "счёт")):
            return False
    return any(w in text for w in _NEW_TOPIC_WORDS)


def should_inherit_intent(message: str, slots: ConversationSlots) -> bool:
    """Короткое follow-up — наследуем active_intent."""
    if not slots.active_intent:
        return False
    text = normalize(message)
    if is_cancel_message(message) or is_new_topic_message(message, slots):
        return False
    if slots.active_intent not in ("payment_create", "payment_order") and extract_payment_hints(message):
        return False
    if slots.active_intent != "employees" and any(
        w in text for w in ("сотрудник", "человек", "работник", "пользовател")
    ):
        return False
    if len(text) > 80:
        return False
    follow_patterns = (
        r"^\d", r"^на\s", r"^за\s", r"^вчера", r"^сегодня",
        r"^[a-z]{3,}\d", r"^\d{4}$", r"^by",
    )
    if any(re.search(p, text) for p in follow_patterns):
        return True
    if len(text.split()) <= 6 and not any(w in text for w in (
        "создай", "открой", "покажи", "перейди", "как ", "что ",
        "добав", "заблок", "закаж", "смен", "помен",
    )):
        return True
    return False


is_follow_up_message = should_inherit_intent


def merge_form_data(slots: ConversationSlots, hints: dict[str, str]) -> ConversationSlots:
    if hints:
        slots.form_data = merge_hints(slots.form_data, hints)
    return slots


def merge_message_hints(
    slots: ConversationSlots,
    message: str,
    screen: str | None = None,
    history: list[dict] | None = None,
) -> ConversationSlots:
    target = screen or slots.target_screen or "instant_payment"
    hints = extract_form_hints(message, target)
    if history:
        hints = merge_hints_from_history(target, message, history, hints)
    return merge_form_data(slots, hints)


def merge_hints_from_history(
    screen: str,
    message: str,
    history: list[dict],
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    merged = dict(base or {})
    merged = merge_hints(merged, extract_form_hints(message, screen))
    for msg in reversed(history[-8:]):
        if msg.get("role") == "user":
            merged = merge_hints(merged, extract_form_hints(msg["content"], screen))
    return merged


def set_active_intent(slots: ConversationSlots, intent: str, screen: str | None = None) -> None:
    new_screen = screen or INTENT_SCREENS.get(intent)
    if slots.target_screen and new_screen and slots.target_screen != new_screen:
        slots.form_data = {}
        slots.pending_account = False
    slots.active_intent = intent
    slots.target_screen = new_screen


def payment_ready(slots: ConversationSlots) -> bool:
    return bool(slots.form_data.get("recipient") and slots.form_data.get("amount"))


def payment_needs_clarification(slots: ConversationSlots) -> bool:
    if slots.active_intent not in ("payment_create", "payment_order"):
        return False
    return not payment_ready(slots)


def build_clarify_payment_text(slots: ConversationSlots) -> str:
    missing = []
    if not slots.form_data.get("recipient"):
        missing.append("получателя")
    if not slots.form_data.get("amount"):
        missing.append("сумму")
    recorded_parts = []
    for key, val in slots.form_data.items():
        recorded_parts.append(f"{key}: {val}")
    prefix = f"Уже записал: {', '.join(recorded_parts)}. " if recorded_parts else ""
    return f"{prefix}Укажите {' и '.join(missing)}."


def statement_ready(slots: ConversationSlots) -> bool:
    return bool(slots.form_data.get("period") or slots.form_data.get("account"))


def resolve_statement_account_id(
    form_data: dict[str, str],
    account: dict,
) -> dict[str, str]:
    """Заменяет IBAN в form_data.account на account ID."""
    updated = dict(form_data)
    acct_val = updated.get("account")
    if acct_val and acct_val != "all":
        if acct_val == account["id"]:
            return updated
        if account_matches(account["number"], acct_val):
            updated["account"] = account["id"]
    return updated


class ConversationSlotsManager:
    def __init__(self, db) -> None:
        self.db = db

    def load(self, conversation_id: str) -> ConversationSlots:
        raw = self.db.get_conversation_slots(conversation_id)
        return ConversationSlots.from_dict(raw)

    def save(self, conversation_id: str, slots: ConversationSlots) -> None:
        self.db.set_conversation_slots(conversation_id, slots.to_dict())
