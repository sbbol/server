"""Контекстная маршрутизация: данные из сообщения + история диалога."""

from app.intent.form_hints import (
    extract_employee_hints,
    extract_form_hints,
    extract_payment_hints,
    extract_statement_hints,
    merge_hints,
)
from app.intent.text_utils import normalize

SCREEN_LABELS = {
    "statement": "Сформировать выписку",
    "instant_payment": "Создать мгновенный платёж",
    "payment_order": "Создать платёжное поручение",
    "employees": "Добавить сотрудника",
    "service_package_form": "Сменить пакет услуг",
}


def _recent_text(history: list[dict], message: str, n: int = 8) -> str:
    parts = [m["content"] for m in history[-n:] if m.get("content")]
    parts.append(message)
    return normalize(" ".join(parts))


def infer_target_screen(message: str, history: list[dict]) -> str | None:
    text = _recent_text(history, message)

    if any(w in text for w in ("выписк", "остаток", "расход")) and "карт" not in text:
        return "statement"
    if "поручен" in text or ("налог" in text and "плат" in text):
        return "payment_order"
    if any(w in text for w in ("мгновен", "мгвен")):
        return "instant_payment"
    if any(w in text for w in ("сотрудник", "пользовател", "работник")) and "банк" not in text:
        return "employees"
    if any(w in text for w in ("тариф", "пакет услуг")):
        return "service_package_form"
    if "реквизит" in text:
        return "account_requisites"
    return None


def try_prefill_from_context(
    message: str,
    history: list[dict],
) -> tuple[str, dict[str, str], str] | None:
    """
    Если пользователь передал данные для формы — определяет экран и поля.
    Возвращает (screen, form_data, label) или None.
    """
    text = normalize(message)
    screen = infer_target_screen(message, history)

    # Явные команды заполнения
    wants_fill = any(
        p in text
        for p in (
            "заполн", "передай", "данн", "сформиру", "сделай",
            "нужно чтобы", "вот этими", "этими данными",
        )
    )

    payment_hints = extract_payment_hints(message)
    statement_hints = extract_statement_hints(message)
    employee_hints = extract_employee_hints(message)

    has_data = bool(payment_hints or statement_hints or employee_hints)

    if not has_data and not wants_fill:
        return None

    if employee_hints and (screen == "employees" or "сотрудник" in text):
        screen = "employees"
        return screen, employee_hints, SCREEN_LABELS["employees"]

    if statement_hints and (screen == "statement" or "выписк" in text or wants_fill):
        screen = "statement"
        # Дополнить из истории если в текущем сообщении только период
        if wants_fill and history:
            for msg in reversed(history[-4:]):
                if msg["role"] == "user":
                    statement_hints = merge_hints(statement_hints, extract_statement_hints(msg["content"]))
        return screen, statement_hints, SCREEN_LABELS["statement"]

    if payment_hints:
        if screen is None or screen == "statement":
            # «100 рублей контрагенту» без контекста — платёж
            if "поручен" in _recent_text(history, message):
                screen = "payment_order"
            else:
                screen = "instant_payment"
        return screen, payment_hints, SCREEN_LABELS.get(screen, "Перейти")

    if wants_fill and screen:
        hints = extract_form_hints(message, screen.replace("_form", "").replace("account_requisites", "statement"))
        if screen == "payment_order":
            hints = merge_hints(hints, extract_payment_hints(message))
        if screen == "instant_payment":
            hints = merge_hints(hints, extract_payment_hints(message))
        if screen == "statement":
            hints = merge_hints(hints, extract_statement_hints(message))
        if hints:
            return screen, hints, SCREEN_LABELS.get(screen, "Перейти")

    return None
