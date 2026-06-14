"""Извлечение данных для предзаполнения форм."""

import re

from app.intent.text_utils import extract_account_hint, normalize


def _extract_quoted(text: str) -> str | None:
    m = re.search(r'["«]([^"»]{2,80})["»]', text)
    return m.group(1).strip() if m else None


def extract_payment_hints(message: str) -> dict[str, str]:
    raw = message
    text = normalize(message)
    hints: dict[str, str] = {}

    # Сумма: 100 рублей, 1000 BYN
    amount = re.search(
        r"сумм\w*\s*(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:руб|р\b|byn|бел\s*руб)?",
        text,
    )
    if not amount:
        amount = re.search(
            r"(?<![a-zа-я])(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:руб|р\b|byn|бел\s*руб)",
            text,
        )
    if amount:
        val = amount.group(1).replace(" ", "").replace(",", ".")
        hints["amount"] = f"{val} BYN" if "руб" in text or "р " in text or text.endswith(" р") else val

    # Номер счёта получателя: ABC123, в кавычках
    acct = re.search(r"номер\s+счет\w*\s+[\"«]?([a-z0-9]{4,20})", text)
    if acct:
        hints["recipient"] = acct.group(1).upper()
    quoted = _extract_quoted(raw)
    if quoted and not hints.get("recipient"):
        if re.match(r"^[a-z0-9]{4,}$", quoted, re.I):
            hints["recipient"] = quoted.upper()
        elif "назначен" not in text[: text.find(quoted.lower()) if quoted.lower() in text else 0]:
            pass

    # Контрагента / получателя Вася
    recipient = re.search(
        r"(?:контрагент\w*|получател\w*|на\s+)([а-яa-z][а-яa-z\s]{1,30}?)(?:\s+на\s+\d|\s*,|\s*$)",
        text,
    )
    if recipient and "recipient" not in hints:
        name = recipient.group(1).strip()
        if name not in ("счет", "счета", "счёт"):
            hints["recipient"] = name.title()

    # Назначение
    purpose = re.search(
        r"назначен\w*\s*[-–:]\s*([^.\n]{1,80})",
        raw,
        re.I,
    )
    if purpose:
        hints["purpose"] = purpose.group(1).strip().rstrip(",")
    elif quoted and re.search(r"назначен", raw, re.I):
        hints["purpose"] = quoted

    # «назначение "Для Андрея"»
    purpose_q = re.search(r'назначен\w*\s+["«]([^"»]+)["»]', raw, re.I)
    if purpose_q:
        hints["purpose"] = purpose_q.group(1).strip()

    # Дата
    if "сегодня" in text:
        hints["payment_date"] = "today"
    elif "вчера" in text:
        hints["payment_date"] = "yesterday"

    return hints


def extract_statement_hints(message: str) -> dict[str, str]:
    text = normalize(message)
    hints: dict[str, str] = {}

    if any(p in text for p in ("все счет", "любой счет", "любой", "по всем", "всех счет")):
        hints["account"] = "all"

    if "вчера" in text:
        hints["period"] = "yesterday"
    elif "сегодня" in text:
        hints["period"] = "today"
    elif "квартал" in text or "расход" in text:
        hints["period"] = "last_quarter"
    elif "месяц" in text:
        hints["period"] = "last_month"
    elif "недел" in text:
        hints["period"] = "last_week"

    acct = extract_account_hint(message)
    if acct:
        hints["account"] = acct

    return hints


def extract_employee_hints(message: str) -> dict[str, str]:
    raw = message
    hints: dict[str, str] = {}

    phone = re.search(r"(\+375\d{9})", raw.replace(" ", ""))
    if phone:
        hints["phone"] = phone.group(1)

    parts = [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]
    for part in parts:
        compact = part.replace(" ", "").replace("-", "")
        if re.match(r"^\+?\d", compact):
            continue
        words = part.split()
        if len(words) >= 2 and all(w[0].isalpha() for w in words[:2]):
            if not hints.get("firstName"):
                hints["firstName"] = words[0].capitalize()
                hints["lastName"] = words[1].capitalize()
                if len(words) >= 3:
                    hints["middleName"] = words[2].capitalize()
        elif len(words) == 1 and len(part) >= 3 and not hints.get("position"):
            hints["position"] = part

    name_match = re.search(
        r"сотрудник\w*\s+([A-Za-zА-Яа-яё]+)\s+([A-Za-zА-Яа-яё]+)",
        raw,
        re.I,
    )
    if name_match:
        hints["firstName"] = name_match.group(1).capitalize()
        hints["lastName"] = name_match.group(2).capitalize()

    return hints


def extract_form_hints(message: str, screen: str) -> dict[str, str]:
    if screen == "statement":
        return extract_statement_hints(message)
    if screen == "employees":
        return extract_employee_hints(message)
    if screen in ("instant_payment", "payment_order"):
        hints = extract_payment_hints(message)
        if screen == "statement":
            hints.update(extract_statement_hints(message))
        return hints
    return {}


def merge_hints(*dicts: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for d in dicts:
        merged.update({k: v for k, v in d.items() if v})
    return merged
