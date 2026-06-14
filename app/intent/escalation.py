"""Контекстная эскалация — только явный запрос оператора банка."""

from app.intent.text_utils import normalize

# Явный запрос живого оператора банка
OPERATOR_REQUEST_PATTERNS = (
    "оператор",
    "оператора",
    "позови оператор",
    "позовите оператор",
    "соедини с оператор",
    "сотрудник банка",
    "сотрудника банка",
    "менеджер банка",
    "живой оператор",
    "живого оператора",
    "служба поддержки",
    "поддержка банка",
    "поговорить с оператор",
    "связать с оператор",
)

# Контекст управления персоналом компании — НЕ эскалация
EMPLOYEE_CONTEXT = (
    "добав", "созда", "новый", "новая", "компани", "организац",
    "кадр", "пользовател", "работник", "штат", "приглас",
)

AGGRESSIVE_PATTERNS = (
    "идиот", "дурак", "тупой", "бесполезн", "отстой", "хрен", "чёрт", "бля",
    "сука", "нахер", "пошёл", "убью",
)


def is_employee_management(message: str) -> bool:
    text = normalize(message)
    if not any(r in text for r in ("сотрудник", "пользовател", "работник", "кадр", "человек")):
        return False
    if any(r in text for r in EMPLOYEE_CONTEXT):
        return True
    if "сотрудник" in text and "банк" not in text and "оператор" not in text:
        return True
    return False


def should_escalate_to_operator(message: str) -> str | None:
    text = normalize(message)

    if any(p in text for p in AGGRESSIVE_PATTERNS):
        return "Агрессивное поведение пользователя"

    if is_employee_management(message):
        return None

    if any(p in text for p in OPERATOR_REQUEST_PATTERNS):
        return "Пользователь запросил оператора"

    # «позови человека» только в банковском контексте
    if "человек" in text and any(p in text for p in ("банк", "оператор", "поддержк", "позов", "соедин")):
        return "Пользователь запросил оператора"

    return None
