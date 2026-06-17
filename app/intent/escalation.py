"""Контекстная эскалация и tiered aggression."""

from __future__ import annotations

from dataclasses import dataclass

from app.intent.text_utils import normalize

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

EMPLOYEE_CONTEXT = (
    "добав", "созда", "новый", "новая", "компани", "организац",
    "кадр", "пользовател", "работник", "штат", "приглас",
)

LEVEL1_PATTERNS = (
    "тупой", "тупая", "блин", "чёрт", "черт", "дурак", "бесполезн", "отстой",
)

LEVEL2_PATTERNS = (
    "идиот", "нахуй", "нахер", "соси", "член", "сука", "хрен", "пошёл", "убью",
    "убить", "убью",
)

EMOTIONAL_DISTRESS_PATTERNS = (
    "не могу больше", "в отчаян", "всё пропало", "все пропало", "кошмар",
    "ужас", "паник", "истерик", "не выдерж", "с ума схож",
)

LEVEL1_RESPONSE = (
    "Понимаю, что ситуация может раздражать. Давайте спокойно разберёмся — я готов помочь."
)
LEVEL2_RESPONSE = (
    "Прошу воздержаться от оскорблений. Если нужна помощь живого сотрудника банка — "
    "напишите «оператор», и я передам диалог."
)


@dataclass
class AggressionAssessment:
    level: int = 0
    reason: str = ""
    response_text: str = ""
    reset_slots: bool = False
    increment_strike: bool = False


def is_employee_management(message: str) -> bool:
    text = normalize(message)

    if "перевед" in text and "сотрудник" in text:
        return False

    if not any(r in text for r in ("сотрудник", "пользовател", "работник", "кадр", "человек")):
        return False
    if any(r in text for r in EMPLOYEE_CONTEXT):
        return True
    if "сотрудник" in text and "банк" not in text and "оператор" not in text:
        return True
    return False


def is_operator_transfer_request(message: str) -> bool:
    text = normalize(message)

    if is_employee_management(message):
        return False

    if any(p in text for p in OPERATOR_REQUEST_PATTERNS):
        return True

    if "перевед" in text and "сотрудник" in text:
        return True

    if "человек" in text and any(p in text for p in ("банк", "оператор", "поддержк", "позов", "соедин")):
        return True

    return False


def assess_aggression(message: str, prior_l2_strikes: int = 0) -> AggressionAssessment:
    text = normalize(message)

    if any(p in text for p in EMOTIONAL_DISTRESS_PATTERNS):
        return AggressionAssessment(
            level=3,
            reason="Эмоциональный срыв пользователя",
            reset_slots=True,
        )

    has_l2 = any(p in text for p in LEVEL2_PATTERNS)
    if has_l2:
        if prior_l2_strikes >= 1:
            return AggressionAssessment(
                level=3,
                reason="Повторная агрессия пользователя",
                reset_slots=True,
            )
        return AggressionAssessment(
            level=2,
            reason="Агрессивное поведение пользователя",
            response_text=LEVEL2_RESPONSE,
            reset_slots=True,
            increment_strike=True,
        )

    if any(p in text for p in LEVEL1_PATTERNS):
        return AggressionAssessment(
            level=1,
            reason="Раздражение пользователя",
            response_text=LEVEL1_RESPONSE,
        )

    return AggressionAssessment()


def should_escalate_to_operator(message: str, prior_l2_strikes: int = 0) -> str | None:
    if is_operator_transfer_request(message):
        return "Пользователь запросил оператора"

    assessment = assess_aggression(message, prior_l2_strikes)
    if assessment.level >= 3:
        return assessment.reason

    return None
