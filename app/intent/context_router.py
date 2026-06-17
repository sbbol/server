"""Контекстная маршрутизация: данные из сообщения + история диалога."""

from app.intent.entities import extract_entities, fresh_hints_for_screen
from app.intent.form_hints import merge_hints
from app.intent.text_utils import is_faq_question, is_question_about_facts, normalize, resolve_account
from app.services.conversation_slots import ConversationSlots, is_follow_up_message

PREFILL_BLOCKERS = ("эцп", "потер", "утер", "ключ", "сертификат", "подпис", "восстанов")

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

    if "карт" in text and any(w in text for w in ("экран", "перейти", "переход", "покаж", "страниц", "открой")):
        return "card_management"

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

    if is_faq_question(message):
        return None

    if any(b in text for b in PREFILL_BLOCKERS):
        return None

    if is_question_about_facts(message) and not any(
        w in text for w in ("плат", "перевод", "оплат", "получател", "контрагент", "поручен")
    ):
        return None

    entities = extract_entities(message, history, skip_if_faq=False)
    screen = infer_target_screen(message, history, slots)

    wants_fill = any(
        p in text
        for p in (
            "заполн", "передай", "данн", "сформиру", "сделай",
            "нужно чтобы", "вот этими", "этими данными",
        )
    )

    fresh_payment = bool(entities.payment_hints)
    fresh_employee = bool(entities.employee_hints)
    fresh_statement = bool(entities.statement_hints)
    fresh_hints = fresh_payment or fresh_employee or fresh_statement

    same_flow = bool(
        slots.target_screen
        and screen == slots.target_screen
        and is_follow_up_message(message, slots)
        and fresh_hints
    )
    base_form = dict(slots.form_data) if same_flow else {}

    payment_hints = merge_hints(base_form, entities.payment_hints)
    statement_hints = merge_hints(base_form, entities.statement_hints)
    employee_hints = merge_hints(base_form, entities.employee_hints)

    if same_flow:
        for msg in reversed(history[-8:]):
            if msg.get("role") == "user":
                prev = extract_entities(msg["content"], skip_if_faq=False)
                payment_hints = merge_hints(payment_hints, prev.payment_hints)
                aid = _resolve_statement_account(user_id, msg["content"], history, db)
                stmt = prev.statement_hints
                if aid and "account" not in stmt:
                    stmt = {**stmt, "account": aid}
                statement_hints = merge_hints(statement_hints, stmt)
                employee_hints = merge_hints(employee_hints, prev.employee_hints)

    has_data = bool(fresh_payment or fresh_employee or (same_flow and base_form))
    if screen == "statement" or "выписк" in text or wants_fill:
        has_data = has_data or bool(fresh_statement)

    if not has_data and not wants_fill:
        return None

    if employee_hints and (screen == "employees" or "сотрудник" in text):
        return "employees", employee_hints, SCREEN_LABELS["employees"]

    if statement_hints and (screen == "statement" or "выписк" in text or wants_fill):
        return "statement", statement_hints, SCREEN_LABELS["statement"]

    payment_screens = {None, "instant_payment", "payment_order"}
    if payment_hints and screen in payment_screens:
        if screen is None or screen == "statement":
            if "поручен" in _recent_text(history, message):
                screen = "payment_order"
            else:
                screen = "instant_payment"
        return screen, payment_hints, SCREEN_LABELS.get(screen, "Перейти")

    if wants_fill and screen:
        hints = fresh_hints_for_screen(message, screen.replace("_form", "").replace("account_requisites", "statement"))
        if screen == "payment_order":
            hints = merge_hints(hints, payment_hints)
        if screen == "instant_payment":
            hints = merge_hints(hints, payment_hints)
        if screen == "statement":
            hints = merge_hints(hints, statement_hints)
        if hints:
            return screen, hints, SCREEN_LABELS.get(screen, "Перейти")

    return None
