"""Формирование детерминированных ответов без LLM."""

from app.intent.text_utils import account_matches, extract_account_hint

GUIDED_PROMPTS = {
    "statement": "Укажите счёт и период (например: «за вчера по всем счетам»), или нажмите кнопку.",
    "instant_payment": "Напишите получателя, сумму и назначение — заполню форму автоматически.",
    "payment_order": "Напишите получателя, сумму и назначение платежа — заполню форму.",
    "employees": "Напишите ФИО, должность и телефон — открою форму с заполненными полями.",
    "service_package_form": "Напишите название пакета услуг или нажмите кнопку для выбора.",
}

FIELD_LABELS = {
    "recipient": "получатель",
    "amount": "сумма",
    "purpose": "назначение",
    "account": "счёт",
    "period": "период",
    "firstName": "имя",
    "lastName": "фамилия",
    "middleName": "отчество",
    "position": "должность",
    "phone": "телефон",
    "email": "email",
    "payment_date": "дата платежа",
    "directorName": "директор",
    "packageName": "пакет",
}


def _format_account_suffix(number: str) -> str:
    digits = "".join(c for c in number if c.isdigit())
    return f"…{digits[-4:]}" if len(digits) >= 4 else number


def _describe_form_fields(form_data: dict[str, str], accounts: list[dict] | None = None) -> str:
    parts: list[str] = []
    for key, val in form_data.items():
        label = FIELD_LABELS.get(key, key)
        if key == "account" and accounts:
            acc = next((a for a in accounts if a["id"] == val), None)
            if acc:
                parts.append(f"{label}: {_format_account_suffix(acc['number'])} ({acc['name']})")
                continue
            if val == "all":
                parts.append(f"{label}: все счета")
                continue
        parts.append(f"{label}: {val}")
    return ", ".join(parts)


def build_account_response(
    tool_text: str,
    account_hint: str | None,
    raw_message: str,
    accounts: list[dict],
) -> str:
    if "нет прав" in tool_text.lower():
        return tool_text

    hint = account_hint or extract_account_hint(raw_message)

    if hint:
        matched = [a for a in accounts if account_matches(a["number"], hint)]
        if not matched:
            return (
                f"Не нашёл счёт, похожий на «{hint}». "
                "Проверьте номер или спросите «покажи все мои счета»."
            )
        if len(matched) == 1:
            a = matched[0]
            balance = a["balance"]
            if balance == "н/д":
                return f"По счёту {_format_account_suffix(a['number'])} ({a['name']}) баланс сейчас недоступен для просмотра."
            return f"На счёте {_format_account_suffix(a['number'])} ({a['name']}): {balance} {a['currency']}."

        lines = [f"По счёту {hint}:"]
        for a in matched:
            bal = f"{a['balance']} {a['currency']}" if a["balance"] != "н/д" else "баланс недоступен"
            lines.append(f"• {a['name']}: {bal}")
        return "\n".join(lines)

    lines = ["Ваши счета:"]
    for a in accounts:
        bal = f"{a['balance']} {a['currency']}" if a["balance"] != "н/д" else "баланс недоступен"
        lines.append(f"• {a['name']}: {bal}")
    return "\n".join(lines)


def build_clarify_account_response(accounts: list[dict]) -> str:
    lines = ["По какому счёту? Уточните, пожалуйста:"]
    for a in accounts:
        if a.get("hidden"):
            continue
        suffix = _format_account_suffix(a["number"])
        bal = f"{a['balance']} {a['currency']}" if a["balance"] != "н/д" else "баланс недоступен"
        lines.append(f"• {a['name']} ({suffix}) — {bal}")
    return "\n".join(lines)


def build_payment_clarify_response(form_data: dict[str, str]) -> str:
    missing = []
    if not form_data.get("recipient"):
        missing.append("получателя")
    if not form_data.get("amount"):
        missing.append("сумму")
    recorded = _describe_form_fields(form_data)
    if missing:
        prefix = f"Уже записал: {recorded}. " if recorded else ""
        return f"{prefix}Укажите {' и '.join(missing)}."
    return ""


def build_drafts_response(drafts: list[dict], with_continue: bool = False) -> str:
    if not drafts:
        return "У вас нет незавершённых черновиков."
    lines = ["Ваши незавершённые черновики:"]
    for d in drafts:
        lines.append(f"• {d['title']} (обновлён {d['updated_at'][:10]})")
    if with_continue:
        lines.append("\nНажмите кнопку ниже, чтобы продолжить с того места, где остановились.")
    return "\n".join(lines)


def build_navigate_response(
    label: str,
    guided: bool = False,
    has_prefill: bool = False,
    screen: str = "",
    form_data: dict[str, str] | None = None,
    accounts: list[dict] | None = None,
) -> str:
    if has_prefill and form_data:
        fields = _describe_form_fields(form_data, accounts)
        return f"Подготовил данные ({fields}). Нажмите «{label}» — поля заполнятся автоматически."
    if has_prefill:
        fields = _describe_prefill(screen)
        return f"Подготовил данные ({fields}). Нажмите «{label}» — поля заполнятся автоматически."
    if guided and screen in GUIDED_PROMPTS:
        return f"{GUIDED_PROMPTS[screen]} Кнопка: «{label}»."
    return f"Конечно, помогу! Нажмите кнопку «{label}» ниже."


def build_prefill_response(
    label: str,
    form_data: dict[str, str],
    screen: str,
    accounts: list[dict] | None = None,
) -> str:
    fields = _describe_form_fields(form_data, accounts)
    return (
        f"Записал: {fields}. "
        f"Нажмите «{label}» — открою форму с заполненными полями."
    )


def _describe_prefill(screen: str) -> str:
    names = {
        "statement": "период и счета",
        "instant_payment": "получатель, сумма, назначение",
        "payment_order": "получатель, сумма, назначение",
        "employees": "ФИО, должность, телефон",
    }
    return names.get(screen, "данные формы")


def build_permission_response(tool_text: str) -> str:
    return tool_text


def build_card_block_response(card_id: str | None, cards: list[dict]) -> str:
    active = [c for c in cards if c["status"] == "active"]
    blocked = [c for c in cards if c["status"] == "blocked"]

    if card_id:
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            return f"Карта {card_id} не найдена."
        if card["status"] == "blocked":
            return f"Карта {card['label']} ({card['name']}) уже заблокирована — блокировать повторно не нужно."
        return f"Готов заблокировать карту {card['label']} ({card['name']}). Нажмите кнопку ниже."

    lines = ["Какую карту заблокировать?"]
    for c in active:
        lines.append(f"• {c['label']} — {c['name']} (активна)")
    for c in blocked:
        lines.append(f"• {c['label']} — {c['name']} (уже заблокирована)")

    if not active and blocked:
        return "Все ваши карты уже заблокированы."
    if not active and not blocked:
        return "У вас нет карт для блокировки."

    lines.append("\nНапишите номер карты (например, 4521) или нажмите кнопку нужной карты.")
    return "\n".join(lines)
