"""Оркестратор: classify → tools → response strategy."""

from app.intent.classifier import classify
from app.intent.context_router import try_prefill_from_context
from app.intent.form_hints import extract_form_hints, merge_hints
from app.intent.models import MatchedIntent, OrchestratorResult, ResponseMode
from app.intent.text_utils import account_matches, extract_account_hint, is_faq_question
from app.services.response_builder import (
    build_account_response,
    build_card_block_response,
    build_drafts_response,
    build_navigate_response,
    build_permission_response,
    build_prefill_response,
)
from app.storage.database import Database
from app.tools.executor import ToolExecutor


class ChatOrchestrator:
    def __init__(self, db: Database) -> None:
        self.db = db

    def plan(
        self,
        message: str,
        user_id: str,
        rag_context: str,
        history: list[dict] | None = None,
    ) -> OrchestratorResult:
        history = history or []
        executor = ToolExecutor(self.db, user_id)
        account_hint = extract_account_hint(message)

        # Контекстное предзаполнение (данные + история)
        prefill_ctx = try_prefill_from_context(message, history)
        if prefill_ctx and not is_faq_question(message):
            screen, form_data, label = prefill_ctx
            text = self._navigate_with_data(executor, screen, label, form_data, message)
            return OrchestratorResult(text=text, actions=executor.pending_actions)

        intents = classify(message)
        primary = intents[0]

        if primary.response_mode == ResponseMode.PERMISSION:
            return OrchestratorResult(
                text=self._run_permission(executor, primary),
                actions=executor.pending_actions,
            )

        if primary.response_mode == ResponseMode.DATA:
            text = self._run_data(executor, primary, message, account_hint)
            return OrchestratorResult(text=text, actions=executor.pending_actions)

        if primary.response_mode == ResponseMode.NAVIGATE and (
            not is_faq_question(message) or primary.guided
        ):
            text = self._run_navigate(executor, primary, message, history)
            return OrchestratorResult(text=text, actions=executor.pending_actions)

        tool_notes = self._run_secondary_tools(intents[1:], executor, message, account_hint, history)
        llm_context = rag_context
        if tool_notes:
            llm_context += f"\n\nДополнительно:\n{tool_notes}"

        return OrchestratorResult(
            text="",
            actions=executor.pending_actions,
            use_llm=True,
            llm_context=llm_context,
        )

    def _navigate_with_data(
        self,
        executor: ToolExecutor,
        screen: str,
        label: str,
        form_data: dict[str, str],
        message: str,
    ) -> str:
        extra: dict = {"form_data": form_data, "params": {"prefill": "true"}}
        if screen == "employees":
            extra["params"]["open"] = "employees"
            extra["params"]["newEmployee"] = "true"
        executor.execute("navigate_to_screen", {
            "screen": screen,
            "label": label,
            **extra,
        })
        return build_prefill_response(label, form_data, screen)

    def _run_permission(self, executor: ToolExecutor, intent: MatchedIntent) -> str:
        action = intent.tool_args.get("action", "")
        from app.permissions import check_permission, permission_denied_message
        if not check_permission(executor.user_id, action):
            return build_permission_response(permission_denied_message(action))
        return "У вас есть права на это действие."

    def _run_data(self, executor: ToolExecutor, intent: MatchedIntent, message: str, hint: str | None) -> str:
        if intent.tool == "get_account_info":
            raw = executor.execute("get_account_info", intent.tool_args)
            accounts = self.db.get_accounts(executor.user_id)
            return build_account_response(raw, hint or intent.tool_args.get("account_hint"), message, accounts)

        if intent.tool == "get_user_drafts":
            drafts = self.db.get_drafts(executor.user_id)
            return build_drafts_response(drafts)

        if intent.tool == "continue_draft":
            drafts = self.db.get_drafts(executor.user_id)
            if not drafts:
                return "Незавершённых черновиков нет."
            draft = self._pick_draft(drafts, message)
            merged = merge_hints(draft.get("form_data") or {}, extract_form_hints(message, draft.get("draft_type", "statement")))
            draft = {**draft, "form_data": merged}
            executor.execute("open_draft", {"draft": draft})
            return build_drafts_response([draft], with_continue=True)

        if intent.tool == "block_card":
            return self._run_block_card(executor, message)

        return executor.execute(intent.tool or "", intent.tool_args)

    def _run_block_card(self, executor: ToolExecutor, message: str) -> str:
        import re
        cards = self.db.get_cards(executor.user_id)
        card_id = None
        m = re.search(r"\b(\d{4})\b", message)
        if m:
            card_id = m.group(1)

        if card_id:
            card = next((c for c in cards if c["id"] == card_id), None)
            if card and card["status"] == "blocked":
                return build_card_block_response(card_id, cards)
            executor.execute("navigate_to_screen", {
                "screen": "card_management",
                "label": f"Заблокировать {card['label'] if card else card_id}",
                "params": {"cardId": card_id, "open": "block"},
            })
            return build_card_block_response(card_id, cards)

        for card in cards:
            if card["status"] == "active":
                executor.execute("navigate_to_screen", {
                    "screen": "card_management",
                    "label": f"Заблокировать {card['label']}",
                    "params": {"cardId": card["id"], "open": "block"},
                })
        return build_card_block_response(None, cards)

    def _pick_draft(self, drafts: list[dict], message: str) -> dict:
        lower = message.lower()
        for d in drafts:
            if d["draft_type"] in lower or d["title"].lower()[:6] in lower:
                return d
            if "выписк" in lower and d["draft_type"] == "statement":
                return d
        return drafts[0]

    def _run_navigate(
        self,
        executor: ToolExecutor,
        intent: MatchedIntent,
        message: str,
        history: list[dict],
    ) -> str:
        args = dict(intent.tool_args or {})
        screen = args.pop("screen", "")
        label = args.pop("label", "Перейти")
        account_id = args.pop("account_id", None)

        form_data = extract_form_hints(message, screen)
        # Дополнить из истории для «сформируй выписку» + «за вчера»
        if intent.guided and history:
            for msg in reversed(history[-3:]):
                if msg["role"] == "user":
                    form_data = merge_hints(form_data, extract_form_hints(msg["content"], screen))

        nav_args: dict = {"screen": screen, "label": label, **args}
        if screen in ("account_view", "account_requisites"):
            nav_args["account_id"] = self._resolve_account_id(
                executor.user_id, message, account_id,
            )
        elif account_id is not None:
            nav_args["account_id"] = account_id
        if form_data:
            nav_args["form_data"] = form_data
            nav_args["params"] = {**(nav_args.get("params") or {}), "prefill": "true"}
        if screen == "employees" and form_data:
            nav_args["params"] = {**(nav_args.get("params") or {}), "open": "employees", "newEmployee": "true"}

        executor.execute("navigate_to_screen", nav_args)
        return build_navigate_response(
            label,
            guided=intent.guided,
            has_prefill=bool(form_data),
            screen=screen,
        )

    def _run_secondary_tools(
        self,
        intents: list[MatchedIntent],
        executor: ToolExecutor,
        message: str,
        hint: str | None,
        history: list[dict],
    ) -> str:
        notes: list[str] = []
        for intent in intents:
            if intent.response_mode == ResponseMode.NAVIGATE:
                notes.append(self._run_navigate(executor, intent, message, history))
            elif intent.response_mode == ResponseMode.DATA:
                notes.append(self._run_data(executor, intent, message, hint))
        return "\n".join(notes)

    def _resolve_account_id(
        self,
        user_id: str,
        message: str,
        fallback: str | None = None,
    ) -> str:
        hint = extract_account_hint(message)
        accounts = self.db.get_accounts(user_id)
        if hint:
            matched = [a for a in accounts if account_matches(a["number"], hint)]
            if matched:
                return matched[0]["id"]
        if fallback:
            return fallback
        return accounts[0]["id"] if accounts else "2"
