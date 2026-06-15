"""Утилиты нормализации текста и извлечения сущностей."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_account(number: str) -> str:
    return re.sub(r"\s+", "", number.upper())


def extract_account_hint(text: str) -> str | None:
    match = re.search(r"BY[\dA-Z\s]{8,}", text, re.IGNORECASE)
    if not match:
        return None
    return normalize_account(match.group())


def extract_account_suffix(text: str) -> str | None:
    """Последние 4 цифры счёта из фраз вроде «оканчивается на 1111»."""
    raw = text
    patterns = [
        r"оканчива\w*\s+на\s+(\d{4})",
        r"счет\w*\s+(?:номер\s+)?(\d{4})",
        r"\.\.\.\s*(\d{4})",
        r"(\d{4})\s*(?:$|[^\d])",
    ]
    for pat in patterns:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def account_matches(stored: str, hint: str, min_overlap: float = 0.55) -> bool:
    """Сопоставляет полный и частичный номер счёта."""
    a = normalize_account(stored)
    b = normalize_account(hint)
    if not a or not b:
        return False
    if a.startswith(b) or b.startswith(a):
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        return len(shorter) / len(longer) >= min_overlap
    return SequenceMatcher(None, shorter, longer).ratio() >= min_overlap


def account_suffix_matches(stored: str, suffix: str) -> bool:
    digits = re.sub(r"\D", "", stored)
    return digits.endswith(suffix)


def contains_substring(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def fuzzy_word_match(text: str, roots: tuple[str, ...], threshold: float = 0.72) -> bool:
    """
    Нечёткое совпадение слов с корнями (опечатки: деняк → деньг).
    Корни короче 4 символов проверяются только как подстрока.
    """
    words = text.split()
    for word in words:
        if len(word) < 3:
            continue
        for root in roots:
            if len(root) < 4:
                if root in word or word in root:
                    return True
                continue
            if root in word or word.startswith(root[: max(3, len(root) - 1)]):
                return True
            if SequenceMatcher(None, word, root).ratio() >= threshold:
                return True
            if len(word) >= 3 and SequenceMatcher(None, word[: len(root)], root).ratio() >= 0.65:
                return True
    return False


def is_question_about_facts(text: str) -> bool:
    """Запрос факта (баланс, сумма), а не инструкции."""
    return contains_substring(text, (
        "сколько", "скаж", "какой", "какая", "какие", "скок",
        "остаток", "баланс", "есть ли", "есть у",
    )) or fuzzy_word_match(text, ("сколько", "скажи", "скажите"))


def is_faq_question(text: str) -> bool:
    """Инструкция / определение — нужен RAG + LLM."""
    normalized = normalize(text)
    if is_tariff_info_question(normalized):
        return True
    if not contains_substring(normalized, (
        "как ", "как?", "что такое", "что значит", "почему", "зачем",
        "объясни", "расскаж", "инструк", "порядок",
    )):
        return False
    if is_question_about_facts(normalized) and not contains_substring(normalized, ("как ", "как?")):
        return False
    return True


def is_tariff_info_question(text: str) -> bool:
    """Информационный вопрос о тарифах — FAQ, не навигация."""
    normalized = normalize(text) if " " not in text or len(text) > 80 else text
    if "тариф" not in normalized and "пакет услуг" not in normalized:
        return False
    return contains_substring(normalized, (
        "какие", "какой", "расскаж", "объясни", "что такое", "есть ли",
        "сколько стоит", "чем отлича",
    )) and not contains_substring(normalized, (
        "сменить", "подключить", "выбрать", "оформ", "перейти",
    ))


is_tariff_faq_question = is_tariff_info_question


def _recent_user_text(message: str, history: list[dict] | None, n: int = 8) -> str:
    parts: list[str] = []
    if history:
        for msg in history[-n:]:
            if msg.get("role") == "user" and msg.get("content"):
                parts.append(msg["content"])
    parts.append(message)
    return " ".join(parts)


@dataclass
class AccountResolveResult:
    status: Literal["found", "not_found", "ambiguous", "none"]
    account: dict | None = None
    candidates: list[dict] | None = None
    message: str = ""


def resolve_account(
    user_id: str,
    message: str,
    history: list[dict] | None,
    db,
    accounts: list[dict] | None = None,
) -> AccountResolveResult:
    """
    Резолв счёта по IBAN, суффиксу, валюте, описанию или no_info.
    """
    accounts = accounts or db.get_accounts(user_id)
    if not accounts:
        return AccountResolveResult(
            status="not_found",
            message="У вас нет доступных счетов.",
        )

    combined = normalize(_recent_user_text(message, history))
    candidates: list[dict] = []

    iban = extract_account_hint(_recent_user_text(message, history))
    if iban:
        exact = [a for a in accounts if normalize_account(a["number"]) == iban]
        candidates = exact if exact else [a for a in accounts if account_matches(a["number"], iban)]

    if not candidates:
        suffix = extract_account_suffix(_recent_user_text(message, history))
        if suffix:
            candidates = [a for a in accounts if account_suffix_matches(a["number"], suffix)]

    if not candidates:
        currency_patterns = (
            (("rub", "рубл", "российск"), "RUB"),
            (("byn", "бел руб", "белорус", "бел "), "BYN"),
        )
        for patterns, code in currency_patterns:
            if contains_substring(combined, patterns):
                matched = [a for a in accounts if a.get("currency", "").upper() == code]
                if matched:
                    candidates = matched
                    break

    if not candidates:
        desc_patterns = (
            ("российск", "рубл"),
            ("специальн",),
            ("расчетн", "текущ"),
            ("строительств", "дорог"),
        )
        for patterns in desc_patterns:
            if contains_substring(combined, patterns):
                matched = []
                for a in accounts:
                    hay = normalize(f"{a.get('name', '')} {a.get('description') or ''}")
                    if any(p in hay for p in patterns):
                        matched.append(a)
                if matched:
                    candidates = matched
                    break

    if not candidates and contains_substring(combined, (
        "без баланса", "баланс недоступен", "недоступен", "н д", "н/д",
    )):
        candidates = [a for a in accounts if a.get("noInfo") or a.get("balance") == "н/д"]

    if not iban and not extract_account_suffix(_recent_user_text(message, history)):
        if not contains_substring(combined, (
            "счет", "счёт", "сч ", "iban", "by", "рубл", "byn", "rub",
            "специальн", "баланс", "реквизит", "выписк", "остаток",
        )):
            return AccountResolveResult(status="none")

    if not candidates:
        return AccountResolveResult(
            status="not_found",
            message="Не удалось определить счёт. Уточните номер (например, «…1111») или название.",
        )

    if len(candidates) == 1:
        a = candidates[0]
        return AccountResolveResult(
            status="found",
            account={
                "id": a["id"],
                "number": a["number"],
                "name": a["name"],
                "currency": a.get("currency", ""),
            },
        )

    return AccountResolveResult(
        status="ambiguous",
        candidates=[
            {
                "id": a["id"],
                "number": a["number"],
                "name": a["name"],
                "currency": a.get("currency", ""),
            }
            for a in candidates
        ],
        message="Найдено несколько подходящих счетов — уточните, пожалуйста.",
    )
