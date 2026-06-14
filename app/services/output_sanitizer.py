"""Очистка ответа LLM от галлюцинированных кнопок и markdown."""

import re


_PATTERNS = [
    re.compile(r"!\[[^\]]*\]\([^)]*\)"),           # ![text](url)
    re.compile(r"!\[[^\]]*\]"),                     # ![text]
    re.compile(r"navigate_to_screen\s*\([^)]*\)", re.I),
    re.compile(r"\[[^\]]*\]\s*\(\s*navigate[^)]*\)", re.I),
    re.compile(r"^Нажмите кнопку ниже:?\s*$", re.I | re.MULTILINE),
    re.compile(r"^Нажмите на кнопку[^.]*\.\s*$", re.I | re.MULTILINE),
]


def sanitize_llm_output(text: str, has_nav_button: bool = False) -> str:
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub("", result)

    result = re.sub(r"\n{3,}", "\n\n", result).strip()

    if not has_nav_button:
        result = re.sub(
            r"([.!?]\s*)?(Нажмите|нажмите)\s+(кнопку|на кнопку)[^.]*\.?",
            "",
            result,
            flags=re.IGNORECASE,
        ).strip()

    return result or "Готов помочь — уточните, пожалуйста, ваш вопрос."
