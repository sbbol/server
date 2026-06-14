"""Определения инструментов (function calling) для Ollama."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Поиск в базе знаний СберБизнес (FAQ, инструкции). Используй для вопросов «как сделать», «что такое», «почему».",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос на русском",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_to_screen",
            "description": "Указать системе, что необходимо показать кнопку для перехода. Не упоминай кнопку в тексте ответа.",
            "parameters": {
                "type": "object",
                "properties": {
                    "screen": {
                        "type": "string",
                        "enum": [
                            "statement",
                            "account_view",
                            "account_requisites",
                            "instant_payment",
                            "payment_order",
                            "card_management",
                            "card_applications",
                            "business_card_form",
                            "corporate_card_form",
                            "service_package_form",
                            "employees",
                            "dashboard",
                        ],
                        "description": "Целевой экран",
                    },
                    "label": {
                        "type": "string",
                        "description": "Текст кнопки, например «Перейти к выпискам»",
                    },
                    "account_id": {
                        "type": "string",
                        "description": "ID счёта (для account_view, account_requisites)",
                    },
                    "params": {
                        "type": "object",
                        "description": "Доп. параметры (период выписки и т.д.)",
                    },
                },
                "required": ["screen", "label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_info",
            "description": "Получить информацию о счетах пользователя (балансы, валюты).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_drafts",
            "description": "Получить незавершённые черновики пользователя для напоминания.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_operator",
            "description": "Передать диалог сотруднику банка. Используй при агрессии, явной просьбе оператора или нерешаемых вопросах.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Причина эскалации",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]

# Маппинг экранов → маршруты клиента
SCREEN_ROUTES: dict[str, dict] = {
    "statement": {"route": "/statement", "permission": "view_statement"},
    "account_view": {"route": "/account_info/{account_id}", "permission": "view_accounts"},
    "account_requisites": {"route": "/account_info/{account_id}", "permission": "view_account_requisites", "params": {"open": "requisites"}},
    "instant_payment": {"route": "/instant-payment", "permission": "create_instant_payment"},
    "payment_order": {"route": "/payment-order", "permission": "create_payment_order"},
    "card_management": {"route": "/products/card-management", "permission": "block_card"},
    "card_applications": {"route": "/products/card-applications", "permission": "order_business_card"},
    "business_card_form": {"route": "/products/business-card-form", "permission": "order_business_card"},
    "corporate_card_form": {"route": "/products/corporate-card-form", "permission": "order_corporate_card"},
    "service_package_form": {"route": "/products/service-package-form", "permission": "change_service_package"},
    "employees": {"route": "/other", "permission": "manage_employees", "params": {"open": "employees"}},
    "dashboard": {"route": "/dashboard", "permission": "view_accounts"},
}
