"""Утилиты нормализации текста и извлечения сущностей."""

import re
from difflib import SequenceMatcher


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
            # корень как начало слова (деньг → деняк: первые 3 символа + fuzzy)
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
    if not contains_substring(normalized, (
        "как ", "как?", "что такое", "что значит", "почему", "зачем",
        "объясни", "расскаж", "инструк", "порядок",
    )):
        return False
    # «как создать платёж» — FAQ, «сколько денег» — нет
    if is_question_about_facts(normalized) and not contains_substring(normalized, ("как ", "как?")):
        return False
    return True
