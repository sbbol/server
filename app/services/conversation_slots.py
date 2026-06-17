"""Накопление контекста диалога (слоты) между сообщениями."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.intent.classifier import classify
from app.intent.form_hints import extract_form_hints, extract_payment_hints, merge_hints
from app.intent.text_utils import normalize


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

INTENT_DOMAINS: dict[str, str] = {
    "payment_create": "payment",
    "payment_order": "payment",
    "statements_filter": "statement",
    "requisites": "account",
    "account_view": "account",
    "account_balance": "account",
    "employees": "employees",
    "service_package": "service_package",
    "card_block": "cards",
}

DOMAIN_TOPIC_WORDS = (
    "эцп", "подпис", "ключ", "сертификат", "потеря", "утеря", "восстанов", "блокиров",
    "сотрудник", "работник", "пользовател", "человек", "команд", "карт", "заблок", "разблок",
    "реквизит", "выписк", "тариф", "пакет услуг", "баланс", "остаток",
    "перевод", "платеж", "платёж", "поручен", "мгновен",
)


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

_CORRECTION_TRIGGERS = (
    "нет", "не тот", "другой", "исправь", "именно", "а не",
)


def is_correction_message(message: str) -> bool:
    text = normalize(message)
    if len(text) > 120:
        return False
    if text.startswith("нет,") or text.startswith("нет "):
        return True
    return any(t in text for t in _CORRECTION_TRIGGERS)


def is_cancel_message(message: str) -> bool:
    text = normalize(message)
    if len(text) > 120:
        return False
    if text in _CANCEL_PHRASES:
        return True
    words = text.split()
    padded = f" {text} "
    for phrase in _CANCEL_PHRASES:
        if len(phrase) <= 3:
            if phrase in words:
                return True
        elif f" {phrase} " in padded or text.startswith(phrase + " ") or text.endswith(" " + phrase):
            return True
    return False


def _intent_domain(intent_id: str) -> str | None:
    return INTENT_DOMAINS.get(intent_id)


def _semantic_topic_shift(message: str, slots: ConversationSlots) -> bool:
    if not slots.active_intent:
        return False
    current_domain = _intent_domain(slots.active_intent)
    if not current_domain:
        return False
    matches = classify(message)
    if not matches or matches[0].intent_id == "faq":
        return False
    new_domain = _intent_domain(matches[0].intent_id)
    if not new_domain:
        return False
    return new_domain != current_domain


def is_new_topic_message(message: str, slots: ConversationSlots | None = None) -> bool:
    text = normalize(message)

    if slots and slots.active_intent in ("payment_create", "payment_order"):
        if any(w in text for w in ("назначен", "получател", "сумм", "руб", "контрагент", "перевод")):
            return False

    if slots and slots.active_intent == "statements_filter":
        if any(w in text for w in ("выписк", "период", "вчера", "месяц", "счет", "счёт")):
            return False

    if any(w in text for w in DOMAIN_TOPIC_WORDS):
        if slots and slots.active_intent:
            if _semantic_topic_shift(message, slots):
                return True
            active_words = {
                "payment_create": ("плат", "перевод", "оплат", "получател", "сумм", "руб", "byn"),
                "payment_order": ("плат", "поручен", "налог", "бюджет"),
                "statements_filter": ("выписк", "период", "расход"),
                "account_balance": ("баланс", "остаток", "счет", "счёт"),
                "account_view": ("счет", "счёт", "операци", "просмотр"),
                "employees": ("сотрудник", "работник", "пользовател", "человек"),
                "card_block": ("карт", "заблок", "блокиров"),
            }.get(slots.active_intent, ())
            if active_words and any(w in text for w in active_words):
                return False
        return True

    if slots and slots.active_intent and _semantic_topic_shift(message, slots):
        return True

    return False


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

    screen = slots.target_screen or INTENT_SCREENS.get(slots.active_intent, "instant_payment")
    if extract_form_hints(message, screen):
        return True

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


def merge_form_data(
    slots: ConversationSlots,
    hints: dict[str, str],
    *,
    correction: bool = False,
) -> ConversationSlots:
    if hints:
        if correction:
            slots.form_data = merge_hints(slots.form_data, hints, force_overwrite=True)
        else:
            slots.form_data = merge_hints(slots.form_data, hints)
    return slots


def merge_message_hints(
    slots: ConversationSlots,
    message: str,
    screen: str | None = None,
    history: list[dict] | None = None,
) -> ConversationSlots:
    target = screen or slots.target_screen or "instant_payment"
    correction = is_correction_message(message)
    hints = extract_form_hints(message, target)
    if correction:
        return merge_form_data(slots, hints, correction=True)
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
    from app.intent.text_utils import account_matches

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
