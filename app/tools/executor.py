"""Исполнение инструментов."""

from app.intent.text_utils import account_matches
from app.permissions import check_permission, permission_denied_message
from app.search.hybrid import format_context, hybrid_search
from app.storage.database import Database
from app.tools.definitions import SCREEN_ROUTES


class ToolExecutor:
    def __init__(self, db: Database, user_id: str) -> None:
        self.db = db
        self.user_id = user_id
        self.pending_actions: list[dict] = []

    def execute(self, name: str, arguments: dict | None = None) -> str:
        arguments = arguments or {}
        if name == "navigate":
            return self._tool_navigate_to_screen(arguments)
        handler = getattr(self, f"_tool_{name}", None)
        if not handler:
            return f"Неизвестный инструмент: {name}"
        return handler(arguments)

    def _tool_search_knowledge_base(self, args: dict) -> str:
        chunks = hybrid_search(args.get("query", ""))
        return format_context(chunks)

    def _tool_navigate_to_screen(self, args: dict) -> str:
        screen = args.get("screen", "")
        label = args.get("label", "Перейти")
        account_id = args.get("account_id")
        if not account_id and screen in ("account_view", "account_requisites"):
            return "Для перехода укажите счёт."
        extra_params = dict(args.get("params") or {})
        form_data = args.get("form_data") or {}

        screen_config = SCREEN_ROUTES.get(screen)
        if not screen_config:
            return f"Экран «{screen}» не найден."

        permission = screen_config["permission"]
        if not check_permission(self.user_id, permission):
            return permission_denied_message(permission)

        route = screen_config["route"]
        if "{account_id}" in route:
            if not account_id:
                return "Для перехода укажите счёт."
            route = route.replace("{account_id}", str(account_id))
        params = {**(screen_config.get("params") or {}), **extra_params}

        action: dict = {
            "type": "navigate",
            "label": label,
            "route": route,
            "params": params,
        }
        if form_data:
            action["form_data"] = form_data

        self.pending_actions.append(action)
        return f"Кнопка «{label}» подготовлена."

    def _tool_open_draft(self, args: dict) -> str:
        draft = args.get("draft", {})
        self.pending_actions.append({
            "type": "navigate",
            "label": f"Продолжить: {draft.get('title', 'черновик')}",
            "route": draft.get("route", "/dashboard"),
            "params": {"prefill": "true"},
            "form_data": draft.get("form_data") or {},
        })
        return "Черновик подготовлен."

    def _tool_get_account_info(self, args: dict) -> str:
        if not check_permission(self.user_id, "view_accounts"):
            return permission_denied_message("view_accounts")

        hint = args.get("account_hint")
        accounts = self.db.get_accounts(self.user_id)
        if hint:
            matched = [a for a in accounts if account_matches(a["number"], hint)]
            if matched:
                accounts = matched

        lines = [f"• {a['name']} ({a['currency']}): {a['balance']}" for a in accounts]
        return "Счета пользователя:\n" + "\n".join(lines)

    def _tool_get_user_drafts(self, _args: dict) -> str:
        drafts = self.db.get_drafts(self.user_id)
        if not drafts:
            return "Незавершённых черновиков нет."
        lines = [f"• {d['title']}" for d in drafts]
        return "Незавершённые черновики:\n" + "\n".join(lines)

    def _tool_escalate_to_operator(self, args: dict) -> str:
        self.pending_actions.append({
            "type": "escalate",
            "reason": args.get("reason", "Запрос пользователя"),
        })
        return "Диалог передан оператору."
