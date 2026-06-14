"""Права пользователя для MVP (один демо-пользователь)."""

from app.config import DEFAULT_USER_ID

# Действия, которые Дэйл может предложить через deep link
ACTION_PERMISSIONS: dict[str, dict[str, bool]] = {
    DEFAULT_USER_ID: {
        "view_accounts": True,
        "view_statement": True,
        "create_instant_payment": True,
        "create_payment_order": True,
        "view_account_requisites": True,
        "block_card": True,
        "order_business_card": True,
        "order_corporate_card": True,
        "manage_employees": True,
        "change_service_package": True,
        "delete_card": False,
        "close_account": False,
        "approve_payments": False,
    }
}

# Человекочитаемые названия для отказа
ACTION_LABELS: dict[str, str] = {
    "delete_card": "удаление карты",
    "close_account": "закрытие счёта",
    "approve_payments": "подписание платежей",
    "block_card": "блокировку карты",
    "manage_employees": "управление сотрудниками",
    "change_service_package": "смену пакета услуг",
    "order_business_card": "заказ бизнес-карты",
    "order_corporate_card": "заказ корпоративной карты",
    "create_instant_payment": "создание мгновенного платежа",
    "create_payment_order": "создание платёжного поручения",
    "view_statement": "просмотр выписки",
    "view_accounts": "просмотр счетов",
    "view_account_requisites": "просмотр реквизитов счёта",
}


def get_permissions(user_id: str) -> dict[str, bool]:
    return ACTION_PERMISSIONS.get(user_id, ACTION_PERMISSIONS[DEFAULT_USER_ID])


def check_permission(user_id: str, action: str) -> bool:
    return get_permissions(user_id).get(action, False)


def permission_denied_message(action: str) -> str:
    label = ACTION_LABELS.get(action, action)
    return (
        f"К сожалению, у вас нет прав на {label}. "
        "Обратитесь к администратору организации для расширения полномочий."
    )
