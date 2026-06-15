"""Извлечение данных для предзаполнения форм."""

import re

from app.intent.text_utils import extract_account_hint, normalize

_EMPLOYEE_SKIP_WORDS = (
    "карт", "тариф", "выписк", "плат", "руб", "byn", "счет", "счёт", "баланс",
    "остаток", "реквизит", "поручен", "мгновен",
)

_EMAIL_RE = re.compile(r"[\w.-]+@[\w.-]+\.\w+")


def _extract_quoted(text: str) -> str | None:
    m = re.search(r'["«]([^"»]{2,80})["»]', text)
    return m.group(1).strip() if m else None


def _looks_like_amount(text: str) -> bool:
    return bool(re.search(r"\d[\d\s]*(?:[.,]\d{1,2})?\s*(?:руб|р\b|byn|бел)", text))


def _should_skip_employee_parse(text: str) -> bool:
    normalized = normalize(text)
    return any(w in normalized for w in _EMPLOYEE_SKIP_WORDS)


def extract_payment_hints(message: str) -> dict[str, str]:
    raw = message
    text = normalize(message)
    hints: dict[str, str] = {}

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
        if "byn" in text or "бел" in text:
            hints["amount"] = f"{val} BYN"
        elif "руб" in text or "р " in text or text.endswith(" р"):
            hints["amount"] = f"{val} RUB"
        else:
            hints["amount"] = val

    acct_patterns = [
        r"(?:на\s+)?счет\w*\s+([a-z0-9]{3,20})",
        r"на\s+([a-z0-9]{3,20})\b",
        r"получател\w*\s+([a-z0-9]{3,20})",
        r"номер\s+счет\w*\s+[\"«]?([a-z0-9]{4,20})",
    ]
    for pat in acct_patterns:
        acct = re.search(pat, text)
        if acct:
            candidate = acct.group(1).upper()
            if candidate.isdigit() and len(candidate) == 4:
                continue
            if not candidate.isdigit() or len(candidate) >= 4:
                hints["recipient"] = candidate
                break

    quoted = _extract_quoted(raw)
    if quoted and not hints.get("recipient"):
        if re.match(r"^[a-z0-9]{4,}$", quoted, re.I):
            hints["recipient"] = quoted.upper()

    recipient = re.search(
        r"(?:контрагент\w*\s+|получател\w*\s+|оплат\w+\s+)([а-яa-z][а-яa-z]{1,20})\b",
        text,
    )
    if recipient and "recipient" not in hints:
        name = recipient.group(1).strip()
        if name not in ("счет", "счета", "счёт", "руб", "рублей") and not name.isdigit():
            if not _looks_like_amount(name):
                hints["recipient"] = name.title()

    name_after = re.search(
        r"(?<![а-яa-z])(\d[\d\s]*(?:[.,]\d{1,2})?\s*(?:руб|р\b|byn)?)\s+([а-яa-z]{2,20})(?:у|а|е|ю|ом|ем)?\b",
        text,
    )
    if name_after and "recipient" not in hints:
        name = name_after.group(2)
        if name not in ("рублей", "руб", "контрагенту", "контрагента", "контрагент"):
            hints["recipient"] = name.title()

    purpose = re.search(r"назначен\w*\s*[-–:]\s*([^.\n]{1,80})", raw, re.I)
    if purpose:
        hints["purpose"] = purpose.group(1).strip().rstrip(",")
    elif quoted and re.search(r"назначен", raw, re.I):
        hints["purpose"] = quoted

    purpose_q = re.search(r'назначен\w*\s+["«]([^"»]+)["»]', raw, re.I)
    if purpose_q:
        hints["purpose"] = purpose_q.group(1).strip()

    if "сегодня" in text:
        hints["payment_date"] = "today"
    elif "вчера" in text:
        hints["payment_date"] = "yesterday"

    return hints


def extract_statement_hints(message: str, account_id: str | None = None) -> dict[str, str]:
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

    if account_id:
        hints["account"] = account_id
    else:
        acct = extract_account_hint(message)
        if acct:
            hints["account"] = acct

    return hints


def extract_employee_hints(message: str) -> dict[str, str]:
    raw = message
    text = normalize(message)
    hints: dict[str, str] = {}

    email = _EMAIL_RE.search(raw)
    if email:
        hints["email"] = email.group(0)

    if _should_skip_employee_parse(message):
        return hints

    phone = re.search(r"(\+375\d{9})", raw.replace(" ", ""))
    if phone:
        hints["phone"] = phone.group(1)

    fio_match = re.search(
        r"\b([А-ЯA-Z][а-яa-z]+)\s+([А-ЯA-Z][а-яa-z]+)(?:\s+([А-ЯA-Z][а-яa-z]+))?\b(?:\s*,\s*([а-яa-z][а-яa-z\s-]{2,40}))?",
        raw,
    )
    if fio_match:
        hints["lastName"] = fio_match.group(1).capitalize()
        hints["firstName"] = fio_match.group(2).capitalize()
        if fio_match.group(3):
            hints["middleName"] = fio_match.group(3).capitalize()
        if fio_match.group(4):
            hints["position"] = fio_match.group(4).strip().capitalize()

    pos_match = re.search(
        r"(?:должност\w*\s*[-–:]?\s*|,\s*)([а-яa-z][а-яa-z\s-]{2,40})",
        raw,
        re.I,
    )
    if pos_match:
        pos = pos_match.group(1).strip().rstrip(".")
        if pos.lower() not in ("email", "телефон"):
            hints["position"] = pos.capitalize() if pos.islower() else pos

    name_match = re.search(
        r"сотрудник\w*\s+([A-Za-zА-Яа-яё]+)\s+([A-Za-zА-Яа-яё]+)",
        raw,
        re.I,
    )
    if name_match and not hints.get("firstName"):
        hints["firstName"] = name_match.group(1).capitalize()
        hints["lastName"] = name_match.group(2).capitalize()

    return hints


def extract_card_form_hints(message: str) -> dict[str, str]:
    raw = message
    hints: dict[str, str] = {}

    phone = re.search(r"(\+375[\d\s()-]{8,})", raw.replace(" ", ""))
    if phone:
        hints["phone"] = re.sub(r"\s+", "", phone.group(1))

    org = re.search(
        r"(?:организац\w*|компани\w*|на\s+карт\w*)\s+([A-Za-z][A-Za-z0-9\s]{1,30})",
        raw,
        re.I,
    )
    if org:
        hints["orgName"] = org.group(1).strip().upper()

    contract = re.search(r"контракт\w*\s*(?:№|#)?\s*(\d[\d/-]*)", raw, re.I)
    if contract:
        hints["contractNumber"] = contract.group(1).strip()

    acct = extract_account_hint(message)
    if acct:
        hints["account"] = acct

    return hints


def extract_service_package_hints(message: str) -> dict[str, str]:
    """Только явные данные директора — без employee-парсера."""
    hints: dict[str, str] = {}
    raw = message

    director = re.search(
        r"(?:директор\w*|руководител\w*)\s+([А-ЯA-Z][а-яa-z]+\s+[А-ЯA-Z][а-яa-z]+(?:\s+[А-ЯA-Z][а-яa-z]+)?)",
        raw,
        re.I,
    )
    if director:
        hints["directorName"] = director.group(1).strip()

    package = re.search(r"(?:пакет|тариф)\s+[\"«]?([^\"»\n,]{2,40})", raw, re.I)
    if package:
        hints["packageName"] = package.group(1).strip()

    return hints


def extract_form_hints(message: str, screen: str) -> dict[str, str]:
    if screen == "statement":
        return extract_statement_hints(message)
    if screen == "employees":
        return extract_employee_hints(message)
    if screen in ("instant_payment", "payment_order"):
        return extract_payment_hints(message)
    if screen in ("business_card_form", "corporate_card_form"):
        return extract_card_form_hints(message)
    if screen == "service_package_form":
        return extract_service_package_hints(message)
    return {}


def merge_hints(*dicts: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for d in dicts:
        for k, v in d.items():
            if not v:
                continue
            if k == "recipient" and _looks_like_amount(v):
                continue
            merged[k] = v
    return merged
