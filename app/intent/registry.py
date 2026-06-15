"""Декларативный реестр намерений."""

from dataclasses import dataclass

from app.intent.models import ResponseMode


@dataclass(frozen=True)
class IntentRule:
    id: str
    response_mode: ResponseMode
    priority: int
    tool: str | None = None
    tool_args: dict | None = None
    any_of: tuple[str, ...] = ()
    fuzzy_roots: tuple[str, ...] = ()
    all_of: tuple[str, ...] = ()
    none_of: tuple[str, ...] = ()
    guided: bool = False  # предложить предзаполнение формы


INTENT_RULES: tuple[IntentRule, ...] = (
    IntentRule(
        id="deny_delete_card",
        response_mode=ResponseMode.PERMISSION,
        priority=100,
        tool="check_permission",
        tool_args={"action": "delete_card"},
        any_of=("удали карту", "удалить карту", "удаление карты"),
    ),
    IntentRule(
        id="account_balance",
        response_mode=ResponseMode.DATA,
        priority=95,
        tool="get_account_info",
        any_of=("баланс", "остаток", "сколько", "скаж", "какой остат"),
        fuzzy_roots=("деньг", "деняк", "денег", "средств", "сумм"),
        none_of=("страниц", "перейти", "переход", "посмотреть", "где", "заполн", "получател", "назначен", "мгновен", "поручен"),
    ),
    IntentRule(
        id="account_balance_by_number",
        response_mode=ResponseMode.DATA,
        priority=94,
        tool="get_account_info",
        all_of=("by",),
        any_of=("сколько", "скаж", "баланс", "остаток", "счет", "счете", "деньг", "деняк"),
    ),
    IntentRule(
        id="list_accounts",
        response_mode=ResponseMode.DATA,
        priority=82,
        tool="get_account_info",
        any_of=("мои счета", "список счет", "все счета", "данные счета", "данные о счет", "покажи счет"),
        none_of=("выписк", "реквизит"),
    ),
    IntentRule(
        id="nav_employees",
        response_mode=ResponseMode.NAVIGATE,
        priority=88,
        tool="navigate",
        tool_args={"screen": "employees", "label": "Добавить сотрудника"},
        any_of=(
            "сотрудник", "добавить сотруд", "добавь сотруд", "новый сотрудник",
            "создать пользовател", "пользователя создать", "новый пользовател",
            "добавить человек", "добавь человек", "человека в команд", "человека для компани", "работник",
        ),
        none_of=("банк", "оператор", "поддержк", "карт", "бизнес", "корпоратив"),
    ),
    IntentRule(
        id="list_drafts",
        response_mode=ResponseMode.DATA,
        priority=87,
        tool="get_user_drafts",
        any_of=("черновик", "незаверш", "бросил", "не законч"),
        none_of=("продолж", "открыть черновик", "дозаполн"),
    ),
    IntentRule(
        id="continue_draft",
        response_mode=ResponseMode.DATA,
        priority=86,
        tool="continue_draft",
        any_of=("продолж", "дозаполн", "открыть черновик", "закончить заполн"),
        fuzzy_roots=("черновик", "выписк"),
    ),
    IntentRule(
        id="nav_expenses_statement",
        response_mode=ResponseMode.NAVIGATE,
        priority=74,
        tool="navigate",
        tool_args={"screen": "statement", "label": "Сформировать выписку"},
        guided=True,
        any_of=("расход", "расходы"),
    ),
    IntentRule(
        id="nav_view_balances",
        response_mode=ResponseMode.NAVIGATE,
        priority=73,
        tool="navigate",
        tool_args={"screen": "account_view", "label": "Просмотреть"},
        any_of=(
            "остаток посмотреть", "посмотреть остаток", "где остаток", "где просмотреть остат",
            "просмотреть", "открой экран просмотр", "детализация по счет",
        ),
        none_of=("выписк", "скачать", "сформир"),
    ),
    IntentRule(
        id="block_card",
        response_mode=ResponseMode.DATA,
        priority=72,
        tool="block_card",
        all_of=("карт",),
        any_of=("заблокир", "блокиров"),
    ),
    IntentRule(
        id="nav_corporate_card",
        response_mode=ResponseMode.NAVIGATE,
        priority=89,
        tool="navigate",
        tool_args={"screen": "corporate_card_form", "label": "Заказать корпоративную карту"},
        any_of=("корпоративн", "корпокарт"),
        none_of=("расход", "выписк", "остаток", "баланс"),
    ),
    IntentRule(
        id="nav_business_card",
        response_mode=ResponseMode.NAVIGATE,
        priority=88,
        tool="navigate",
        tool_args={"screen": "business_card_form", "label": "Заказать бизнес-карту"},
        any_of=("бизнес карт", "бизнескарт", "создай бизнес", "создать бизнес"),
        none_of=("сотрудник", "пользовател", "работник"),
    ),
    IntentRule(
        id="nav_order_card",
        response_mode=ResponseMode.NAVIGATE,
        priority=69,
        tool="navigate",
        tool_args={"screen": "card_applications", "label": "Заказать карту"},
        any_of=("заказать карт", "получить карт", "оформить карт", "новую карт", "карту получ"),
        none_of=("заблокир", "блокиров"),
    ),
    IntentRule(
        id="nav_payment_order",
        response_mode=ResponseMode.NAVIGATE,
        priority=68,
        tool="navigate",
        tool_args={"screen": "payment_order", "label": "Создать платёжное поручение"},
        guided=True,
        any_of=(
            "платежное поручение", "платежное поручение", "платежку", "платежку",
            "поручен", "налог", "бюджет", "в бюджет",
        ),
        none_of=("мгновен", "мгвен"),
    ),
    IntentRule(
        id="nav_statement",
        response_mode=ResponseMode.NAVIGATE,
        priority=67,
        tool="navigate",
        tool_args={"screen": "statement", "label": "Сформировать выписку"},
        guided=True,
        any_of=("выписк", "скачать выписк", "получить выписк", "сформир"),
        none_of=("сколько", "баланс", "остаток", "продолж", "просмотреть", "просмотр"),
    ),
    IntentRule(
        id="nav_instant_payment",
        response_mode=ResponseMode.NAVIGATE,
        priority=66,
        tool="navigate",
        tool_args={"screen": "instant_payment", "label": "Создать мгновенный платёж"},
        guided=True,
        any_of=("мгновен", "мгвен"),
        fuzzy_roots=("плат", "плот", "перевод", "оплат"),
    ),
    IntentRule(
        id="nav_instant_payment_action",
        response_mode=ResponseMode.NAVIGATE,
        priority=65,
        tool="navigate",
        tool_args={"screen": "instant_payment", "label": "Создать платёж"},
        guided=True,
        fuzzy_roots=("плат", "плот", "оплат", "перевод"),
        any_of=("создать", "сделать", "произвест", "оформ", "помог", "нужно", "налог"),
        none_of=("поручен", "выписк", "баланс", "сколько", "остаток", "пользовател", "сотрудник", "бюджет"),
    ),
    IntentRule(
        id="nav_service_package",
        response_mode=ResponseMode.NAVIGATE,
        priority=64,
        tool="navigate",
        tool_args={"screen": "service_package_form", "label": "Сменить пакет услуг"},
        guided=True,
        any_of=("сменить пакет", "выбрать пакет", "подключить услуг", "подключить пакет", "сменить тариф", "подключить тариф"),
        none_of=("какие", "расскаж", "что такое", "объясни", "про тариф", "есть ли"),
    ),
    IntentRule(
        id="nav_requisites",
        response_mode=ResponseMode.NAVIGATE,
        priority=63,
        tool="navigate",
        tool_args={"screen": "account_requisites", "label": "Показать реквизиты"},
        any_of=("реквизит", "модальн"),
    ),
    IntentRule(
        id="nav_account_view",
        response_mode=ResponseMode.NAVIGATE,
        priority=72,
        tool="navigate",
        tool_args={"screen": "account_view", "label": "Просмотреть"},
        any_of=(
            "просмотреть сч", "операции по сч", "деньги и событ",
            "страниц", "перейти", "переход", "данные о счет",
            "открой экран", "детализация по счет",
        ),
        none_of=("сколько", "баланс", "остаток", "реквизит", "выписк"),
    ),
)
