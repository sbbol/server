"""Единое извлечение сущностей из сообщения."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.intent.form_hints import (
    extract_card_form_hints,
    extract_employee_hints,
    extract_form_hints,
    extract_payment_hints,
    extract_statement_hints,
)
from app.intent.text_utils import is_faq_question, normalize

ECP_BLOCKERS = ("эцп", "подпис", "ключ", "сертификат", "потер", "утер", "восстанов")
TOPIC_ECP = ("эцп", "подпис", "ключ", "сертификат", "потер", "утер", "восстанов", "clientsign")
TOPIC_CARDS = ("карт", "бизнес карт", "корпоративн")
TOPIC_PAYMENTS = ("плат", "перевод", "оплат", "поручен", "мгновен")
TOPIC_STATEMENTS = ("выписк", "расход", "операци")


@dataclass
class Entities:
    amount: str | None = None
    currency: str | None = None
    recipient: str | None = None
    purpose: str | None = None
    period: str | None = None
    account: str | None = None
    person_name: str | None = None
    position: str | None = None
    phone: str | None = None
    email: str | None = None
    card_id: str | None = None
    card_action: str | None = None
    topic_keywords: set[str] = field(default_factory=set)
    payment_hints: dict[str, str] = field(default_factory=dict)
    statement_hints: dict[str, str] = field(default_factory=dict)
    employee_hints: dict[str, str] = field(default_factory=dict)
    card_hints: dict[str, str] = field(default_factory=dict)


def _detect_topics(text: str) -> set[str]:
    topics: set[str] = set()
    if any(t in text for t in TOPIC_ECP):
        topics.add("ecps")
    if any(t in text for t in TOPIC_CARDS):
        topics.add("cards")
    if any(t in text for t in TOPIC_PAYMENTS):
        topics.add("payments")
    if any(t in text for t in TOPIC_STATEMENTS):
        topics.add("statements")
    return topics


def _has_ecp_topic(text: str) -> bool:
    return any(t in text for t in ECP_BLOCKERS)


def _parse_amount_currency(hints: dict[str, str]) -> tuple[str | None, str | None]:
    raw = hints.get("amount", "")
    if not raw:
        return None, None
    m = re.match(r"([\d.]+)\s*(RUB|BYN)?", raw, re.I)
    if m:
        return m.group(1), (m.group(2) or "").upper() or None
    return raw, None


def extract_entities(
    message: str,
    history: list[dict] | None = None,
    *,
    skip_if_faq: bool = True,
) -> Entities:
    text = normalize(message)
    topics = _detect_topics(text)

    if skip_if_faq and is_faq_question(message):
        return Entities(topic_keywords=topics)

    if _has_ecp_topic(text):
        return Entities(topic_keywords=topics | {"ecps"})

    payment_hints = extract_payment_hints(message)
    statement_hints = extract_statement_hints(message)
    employee_hints = extract_employee_hints(message)
    card_hints = extract_card_form_hints(message)

    amount, currency = _parse_amount_currency(payment_hints)
    recipient = payment_hints.get("recipient")
    person_name = None
    if employee_hints.get("firstName"):
        parts = [
            employee_hints.get("lastName", ""),
            employee_hints.get("firstName", ""),
            employee_hints.get("middleName", ""),
        ]
        person_name = " ".join(p for p in parts if p).strip() or None

    card_id = None
    card_action = None
    m = re.search(r"\b(\d{4})\b", message)
    if m and "карт" in text:
        card_id = m.group(1)
    if any(w in text for w in ("заблокир", "блокиров")):
        card_action = "block"
    elif any(w in text for w in ("разблокир",)):
        card_action = "unblock"

    return Entities(
        amount=amount,
        currency=currency,
        recipient=recipient,
        purpose=payment_hints.get("purpose"),
        period=statement_hints.get("period"),
        account=statement_hints.get("account") or card_hints.get("account"),
        person_name=person_name,
        position=employee_hints.get("position"),
        phone=employee_hints.get("phone") or card_hints.get("phone"),
        email=employee_hints.get("email"),
        card_id=card_id,
        card_action=card_action,
        topic_keywords=topics,
        payment_hints=payment_hints,
        statement_hints=statement_hints,
        employee_hints=employee_hints,
        card_hints=card_hints,
    )


def fresh_hints_for_screen(message: str, screen: str) -> dict[str, str]:
    """Подсказки формы только из текущего сообщения."""
    return extract_form_hints(message, screen)
