"""Контекстная маршрутизация: данные из сообщения + история диалога."""

import json
import time
from pathlib import Path

from app.intent.form_hints import (
    extract_employee_hints,
    extract_form_hints,
    extract_payment_hints,
    extract_statement_hints,
    merge_hints,
)
from app.intent.text_utils import is_question_about_facts, normalize, resolve_account
from app.services.conversation_slots import ConversationSlots, is_follow_up_message, merge_message_hints

_DBG_LOG = Path(__file__).resolve().parent.parent.parent / "debug-1344f1.log"


def _dbg(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "1344f1",
            "location": location,
            "message": message,
            "data": data,
            "hypothesisId": hypothesis_id,
            "timestamp": int(time.time() * 1000),
        }
        with _DBG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


SCREEN_LABELS = {
    "statement": "Сформировать выписку",
    "instant_payment": "Создать мгновенный платёж",
    "payment_order": "Создать платёжное поручение",
    "employees": "Добавить сотрудника",
    "service_package_form": "Сменить пакет услуг",
    "account_view": "Просмотреть",
    "account_requisites": "Показать реквизиты",
}


def _recent_text(history: list[dict], message: str, n: int = 8) -> str:
    parts = [m["content"] for m in history[-n:] if m.get("content")]
    parts.append(message)
    return normalize(" ".join(parts))


def infer_target_screen(message: str, history: list[dict], slots: ConversationSlots | None = None) -> str | None:
    if slots and is_follow_up_message(message, slots) and slots.target_screen:
        return slots.target_screen

    text = _recent_text(history, message)

    if "реквизит" in text:
        return "account_requisites"

    if "выписк" in text or ("расход" in text and "карт" not in text):
        return "statement"

    if contains_view_intent(text) and "выписк" not in text:
        return "account_view"

    if "остаток" in text or "баланс" in text:
        if "выписк" in text:
            return "statement"
        if contains_view_intent(text):
            return "account_view"

    if "поручен" in text or ("налог" in text and "плат" in text):
        return "payment_order"
    if any(w in text for w in ("мгновен", "мгвен")):
        return "instant_payment"
    if any(w in text for w in ("сотрудник", "пользовател", "работник", "человек", "команд")) and "банк" not in text:
        return "employees"
    if any(w in text for w in ("тариф", "пакет услуг")) and not is_tariff_action(text):
        return None
    if any(w in text for w in ("тариф", "пакет услуг")):
        return "service_package_form"
    return None


def contains_view_intent(text: str) -> bool:
    return any(w in text for w in (
        "просмотр", "открой", "открыть", "экран", "операци", "детализац",
    ))


def is_tariff_action(text: str) -> bool:
    return any(w in text for w in ("сменить", "подключить", "выбрать", "оформ"))


def _resolve_statement_account(user_id, message, history, db) -> str | None:
    result = resolve_account(user_id, message, history, db)
    if result.status == "found" and result.account:
        return result.account["id"]
    return None


def try_prefill_from_context(
    message: str,
    history: list[dict],
    user_id: str,
    db,
    slots: ConversationSlots | None = None,
) -> tuple[str, dict[str, str], str] | None:
    """
    Если пользователь передал данные для формы — определяет экран и поля.
    Возвращает (screen, form_data, label) или None.
    """
    slots = slots or ConversationSlots()
    text = normalize(message)

    if is_question_about_facts(message) and not any(
        w in text for w in ("плат", "перевод", "оплат", "получател", "контрагент", "поручен")
    ):
        return None

    screen = infer_target_screen(message, history, slots)

    wants_fill = any(
        p in text
        for p in (
            "заполн", "передай", "данн", "сформиру", "сделай",
            "нужно чтобы", "вот этими", "этими данными",
        )
    )

    same_flow = bool(
        slots.target_screen
        and screen == slots.target_screen
        and is_follow_up_message(message, slots)
    )
    base_form = dict(slots.form_data) if same_flow else {}

    msg_payment = extract_payment_hints(message)
    account_id = _resolve_statement_account(user_id, message, history, db)
    msg_statement = extract_statement_hints(message, account_id=account_id)
    msg_employee = extract_employee_hints(message)

    payment_hints = merge_hints(base_form, msg_payment)
    statement_hints = merge_hints(base_form, msg_statement)
    employee_hints = merge_hints(base_form, msg_employee)

    if same_flow:
        for msg in reversed(history[-8:]):
            if msg.get("role") == "user":
                payment_hints = merge_hints(payment_hints, extract_payment_hints(msg["content"]))
                aid = _resolve_statement_account(user_id, msg["content"], history, db)
                statement_hints = merge_hints(
                    statement_hints,
                    extract_statement_hints(msg["content"], account_id=aid),
                )
                employee_hints = merge_hints(employee_hints, extract_employee_hints(msg["content"]))

    has_data = bool(msg_payment or msg_employee or (same_flow and base_form))
    if screen == "statement" or "выписк" in text or wants_fill:
        has_data = has_data or bool(msg_statement)
    stale_from_slots = bool(base_form)
    fresh_payment = bool(msg_payment)
    fresh_employee = bool(msg_employee)
    fresh_statement = bool(msg_statement)

    # #region agent log
    _dbg(
        "context_router.py:try_prefill",
        "prefill_analysis",
        {
            "message": message[:120],
            "screen": screen,
            "has_data": has_data,
            "stale_from_slots": stale_from_slots,
            "base_form_keys": list(base_form.keys()),
            "payment_keys": list(payment_hints.keys()),
            "employee_keys": list(employee_hints.keys()),
            "statement_keys": list(statement_hints.keys()),
            "fresh_payment": fresh_payment,
            "fresh_employee": fresh_employee,
            "fresh_statement": fresh_statement,
            "wants_fill": wants_fill,
        },
        "A",
    )
    # #endregion

    if not has_data and not wants_fill:
        return None

    if employee_hints and (screen == "employees" or "сотрудник" in text):
        # #region agent log
        _dbg("context_router.py:try_prefill", "route_employees", {"employee_keys": list(employee_hints.keys())}, "A")
        # #endregion
        return "employees", employee_hints, SCREEN_LABELS["employees"]

    if statement_hints and (screen == "statement" or "выписк" in text or wants_fill):
        # #region agent log
        _dbg("context_router.py:try_prefill", "route_statement", {"statement_keys": list(statement_hints.keys())}, "A")
        # #endregion
        return "statement", statement_hints, SCREEN_LABELS["statement"]

    payment_screens = {None, "instant_payment", "payment_order"}
    if payment_hints and screen in payment_screens:
        if screen is None or screen == "statement":
            if "поручен" in _recent_text(history, message):
                screen = "payment_order"
            else:
                screen = "instant_payment"
        # #region agent log
        _dbg(
            "context_router.py:try_prefill",
            "route_payment",
            {"screen": screen, "payment_keys": list(payment_hints.keys()), "inferred_screen": screen},
            "A",
        )
        # #endregion
        return screen, payment_hints, SCREEN_LABELS.get(screen, "Перейти")

    if wants_fill and screen:
        hints = extract_form_hints(message, screen.replace("_form", "").replace("account_requisites", "statement"))
        if screen == "payment_order":
            hints = merge_hints(hints, payment_hints)
        if screen == "instant_payment":
            hints = merge_hints(hints, payment_hints)
        if screen == "statement":
            hints = merge_hints(hints, statement_hints)
        if hints:
            return screen, hints, SCREEN_LABELS.get(screen, "Перейти")

    return None
