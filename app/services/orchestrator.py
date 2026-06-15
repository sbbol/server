"""Оркестратор: route → tools → response strategy."""

import logging

from app.intent.context_router import try_prefill_from_context
from app.intent.form_hints import extract_statement_hints, merge_hints
from app.intent.models import MatchedIntent, OrchestratorResult, ResponseMode
from app.intent.router import route_message
from app.intent.text_utils import (
    account_matches,
    extract_account_hint,
    normalize,
    resolve_account,
)
from app.services.conversation_slots import (
    ConversationSlots,
    ConversationSlotsManager,
    merge_message_hints,
    payment_ready,
    set_active_intent,
)
from app.services.response_builder import (
    build_account_response,
    build_card_block_response,
    build_clarify_account_response,
    build_drafts_response,
    build_navigate_response,
    build_payment_clarify_response,
    build_permission_response,
    build_prefill_response,
)
from app.storage.database import Database
from app.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

ACCOUNT_SCREENS = frozenset({"account_view", "account_requisites", "statement"})
NAV_CONFIDENCE_THRESHOLD = 0.85


class ChatOrchestrator:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.slots_manager = ConversationSlotsManager(db)

    def plan(
        self,
        message: str,
        user_id: str,
        rag_context: str,
        history: list[dict] | None = None,
        conversation_id: str | None = None,
        slots: ConversationSlots | None = None,
    ) -> tuple[OrchestratorResult, ConversationSlots]:
        history = history or []
        slots = slots or ConversationSlots()
        executor = ToolExecutor(self.db, user_id)
        accounts = self.db.get_accounts(user_id)

        decision = route_message(message, history, slots)
        logger.info(
            "route_decision mode=%s confidence=%.2f reason=%s",
            decision.mode,
            decision.confidence,
            decision.reason,
            extra={
                "route_decision": {
                    "mode": decision.mode,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                    "active_intent": slots.active_intent,
                },
            },
        )

        if decision.reset_slots:
            if decision.reason == "cancel_message":
                return OrchestratorResult(
                    text="Хорошо, отменил предыдущий запрос. Чем ещё могу помочь?",
                    actions=[],
                ), ConversationSlots(last_card_intent=slots.last_card_intent)
            slots = ConversationSlots(last_card_intent=slots.last_card_intent)

        if decision.mode == "FAQ":
            return OrchestratorResult(
                text="",
                actions=[],
                use_llm=True,
                llm_context=rag_context,
            ), slots

        if decision.mode == "ESCALATE":
            return OrchestratorResult(
                text="",
                actions=[{"type": "escalate", "reason": decision.reason}],
            ), ConversationSlots()

        follow_up = bool(slots.active_intent) and decision.reason not in ("topic_shift", "topic_shift_faq")
        if follow_up and slots.active_intent:
            slots = merge_message_hints(slots, message, slots.target_screen, history)

        prefill_ctx = try_prefill_from_context(message, history, user_id, self.db, slots)
        if prefill_ctx and decision.mode == "TOOL":
            screen, form_data, label = prefill_ctx
            set_active_intent(slots, _screen_to_intent(screen), screen)
            slots.form_data = merge_hints(slots.form_data, form_data)

            if screen == "statement":
                resolved = self._resolve_for_screen(user_id, message, history, accounts, require_account=True)
                if resolved.get("clarify"):
                    return OrchestratorResult(text=resolved["clarify"], actions=[]), slots
                if resolved.get("account_id"):
                    form_data = {**form_data, "account": resolved["account_id"]}
                    slots.form_data["account"] = resolved["account_id"]

            if screen in ("instant_payment", "payment_order") and not payment_ready(slots):
                clarify = build_payment_clarify_response(slots.form_data)
                if clarify and "открой" not in normalize(message):
                    return OrchestratorResult(text=clarify, actions=[]), slots

            text = self._navigate_with_data(
                executor, screen, label, form_data, message, history, accounts,
            )
            return OrchestratorResult(text=text, actions=executor.pending_actions), slots

        intents = decision.intents
        primary = intents[0]

        if primary.response_mode == ResponseMode.PERMISSION:
            return OrchestratorResult(
                text=self._run_permission(executor, primary),
                actions=executor.pending_actions,
            ), slots

        if primary.response_mode == ResponseMode.DATA:
            text, actions = self._run_data(
                executor, primary, message, history, user_id, accounts, slots, conversation_id,
            )
            return OrchestratorResult(text=text, actions=actions or executor.pending_actions), slots

        if primary.response_mode == ResponseMode.NAVIGATE and primary.score >= NAV_CONFIDENCE_THRESHOLD:
            text = self._run_navigate(
                executor, primary, message, history, user_id, accounts, slots, conversation_id,
            )
            return OrchestratorResult(text=text, actions=executor.pending_actions), slots

        tool_notes = self._run_secondary_tools(
            intents[1:],
            executor,
            message,
            history,
            user_id,
            accounts,
            slots,
            conversation_id,
            min_score=NAV_CONFIDENCE_THRESHOLD,
        )
        llm_context = rag_context
        if tool_notes:
            llm_context += f"\n\nДополнительно:\n{tool_notes}"

        return OrchestratorResult(
            text="",
            actions=executor.pending_actions,
            use_llm=True,
            llm_context=llm_context,
        ), slots

    def _resolve_for_screen(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        accounts: list[dict],
        require_account: bool = False,
    ) -> dict:
        result = resolve_account(user_id, message, history, self.db, accounts)
        if result.status == "found" and result.account:
            return {"account_id": result.account["id"]}
        if result.status == "ambiguous":
            return {"clarify": build_clarify_account_response(
                [a for a in accounts if a["id"] in {c["id"] for c in (result.candidates or [])}]
                or accounts,
            )}
        if result.status == "not_found" and require_account and len(accounts) > 1:
            return {"clarify": build_clarify_account_response(accounts)}
        if result.status == "none" and require_account and len(accounts) > 1:
            return {"clarify": build_clarify_account_response(accounts)}
        return {}

    def _navigate_with_data(
        self,
        executor: ToolExecutor,
        screen: str,
        label: str,
        form_data: dict[str, str],
        message: str,
        history: list[dict],
        accounts: list[dict],
    ) -> str:
        extra: dict = {"form_data": form_data, "params": {"prefill": "true"}}
        nav_args: dict = {"screen": screen, "label": label, **extra}

        if screen in ("account_view", "account_requisites"):
            resolved = self._resolve_for_screen(
                executor.user_id, message, history, accounts, require_account=True,
            )
            if resolved.get("clarify"):
                return resolved["clarify"]
            if resolved.get("account_id"):
                nav_args["account_id"] = resolved["account_id"]
        elif screen == "employees":
            nav_args["params"]["open"] = "employees"
            nav_args["params"]["newEmployee"] = "true"

        executor.execute("navigate_to_screen", nav_args)
        return build_prefill_response(label, form_data, screen, accounts)

    def _run_permission(self, executor: ToolExecutor, intent: MatchedIntent) -> str:
        action = intent.tool_args.get("action", "")
        from app.permissions import check_permission, permission_denied_message
        if not check_permission(executor.user_id, action):
            return build_permission_response(permission_denied_message(action))
        return "У вас есть права на это действие."

    def _run_data(
        self,
        executor: ToolExecutor,
        intent: MatchedIntent,
        message: str,
        history: list[dict],
        user_id: str,
        accounts: list[dict],
        slots: ConversationSlots,
        conversation_id: str | None,
    ) -> tuple[str, list[dict]]:
        if intent.tool == "get_account_info":
            raw = executor.execute("get_account_info", intent.tool_args)
            hint = intent.tool_args.get("account_hint") or extract_account_hint(message)
            if not hint:
                resolved = resolve_account(user_id, message, history, self.db, accounts)
                if resolved.status == "found" and resolved.account:
                    hint = resolved.account["number"]

            text = build_account_response(raw, hint, message, accounts)

            if intent.intent_id in ("account_balance", "account_balance_by_number"):
                set_active_intent(slots, "account_balance", "account_view")
                resolved = resolve_account(user_id, message, history, self.db, accounts)
                if resolved.status == "found" and resolved.account:
                    executor.execute("navigate_to_screen", {
                        "screen": "account_view",
                        "label": "Просмотреть",
                        "account_id": resolved.account["id"],
                    })
                elif resolved.status == "ambiguous":
                    text += "\n\n" + build_clarify_account_response(
                        [a for a in accounts if a["id"] in {c["id"] for c in (resolved.candidates or [])}],
                    )
            return text, executor.pending_actions

        if intent.tool == "get_user_drafts":
            drafts = self.db.get_drafts(executor.user_id)
            return build_drafts_response(drafts), executor.pending_actions

        if intent.tool == "continue_draft":
            from app.intent.form_hints import extract_form_hints

            drafts = self.db.get_drafts(executor.user_id)
            if not drafts:
                return "Незавершённых черновиков нет.", executor.pending_actions
            draft = self._pick_draft(drafts, message)
            merged = merge_hints(draft.get("form_data") or {}, extract_form_hints(message, draft.get("draft_type", "statement")))
            draft = {**draft, "form_data": merged}
            executor.execute("open_draft", {"draft": draft})
            return build_drafts_response([draft], with_continue=True), executor.pending_actions

        if intent.tool == "block_card":
            slots.last_card_intent = "block_card"
            set_active_intent(slots, "card_block", "card_management")
            return self._run_block_card(executor, message, slots), executor.pending_actions

        return executor.execute(intent.tool or "", intent.tool_args), executor.pending_actions

    def _run_block_card(self, executor: ToolExecutor, message: str, slots: ConversationSlots) -> str:
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

        active = [c for c in cards if c["status"] == "active"]
        if slots.last_card_intent == "block_card" and active:
            for card in active:
                executor.execute("navigate_to_screen", {
                    "screen": "card_management",
                    "label": f"Заблокировать {card['label']}",
                    "params": {"cardId": card["id"], "open": "block"},
                })
            return build_card_block_response(None, cards)

        for card in active:
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
        user_id: str,
        accounts: list[dict],
        slots: ConversationSlots,
        conversation_id: str | None,
    ) -> str:
        args = dict(intent.tool_args or {})
        screen = args.pop("screen", "")
        label = args.pop("label", "Перейти")
        account_id = args.pop("account_id", None)

        set_active_intent(slots, intent.intent_id, screen)
        slots = merge_message_hints(slots, message, screen, history)
        form_data = dict(slots.form_data)

        if screen == "statement":
            resolved = self._resolve_for_screen(user_id, message, history, accounts, require_account=True)
            if resolved.get("clarify"):
                slots.pending_account = True
                return resolved["clarify"]
            if resolved.get("account_id"):
                form_data["account"] = resolved["account_id"]
                slots.form_data["account"] = resolved["account_id"]
            elif "account" not in form_data:
                stmt_hints = extract_statement_hints(message)
                for msg in reversed(history[-8:]):
                    if msg.get("role") == "user":
                        stmt_hints = merge_hints(stmt_hints, extract_statement_hints(msg["content"]))
                form_data = merge_hints(form_data, stmt_hints)

        nav_args: dict = {"screen": screen, "label": label, **args}

        if screen in ("account_view", "account_requisites"):
            resolved = self._resolve_for_screen(user_id, message, history, accounts, require_account=True)
            if resolved.get("clarify"):
                slots.pending_account = True
                return resolved["clarify"]
            nav_args["account_id"] = resolved.get("account_id") or account_id
        elif account_id is not None:
            nav_args["account_id"] = account_id

        if form_data:
            nav_args["form_data"] = form_data
            nav_args["params"] = {**(nav_args.get("params") or {}), "prefill": "true"}
            slots.form_data = form_data

        if screen == "employees" and form_data:
            nav_args["params"] = {**(nav_args.get("params") or {}), "open": "employees", "newEmployee": "true"}

        if screen == "account_requisites":
            nav_args["params"] = {**(nav_args.get("params") or {}), "open": "requisites"}

        if screen in ("instant_payment", "payment_order") and not payment_ready(slots):
            clarify = build_payment_clarify_response(slots.form_data)
            if clarify:
                return clarify

        executor.execute("navigate_to_screen", nav_args)
        return build_navigate_response(
            label,
            guided=intent.guided,
            has_prefill=bool(form_data),
            screen=screen,
            form_data=form_data,
            accounts=accounts,
        )

    def _run_secondary_tools(
        self,
        intents: list[MatchedIntent],
        executor: ToolExecutor,
        message: str,
        history: list[dict],
        user_id: str,
        accounts: list[dict],
        slots: ConversationSlots,
        conversation_id: str | None,
        min_score: float = 0.0,
    ) -> str:
        notes: list[str] = []
        for intent in intents:
            if intent.score < min_score:
                continue
            if intent.response_mode == ResponseMode.NAVIGATE:
                notes.append(self._run_navigate(
                    executor, intent, message, history, user_id, accounts, slots, conversation_id,
                ))
            elif intent.response_mode == ResponseMode.DATA:
                note, _ = self._run_data(
                    executor, intent, message, history, user_id, accounts, slots, conversation_id,
                )
                notes.append(note)
        return "\n".join(notes)


def _screen_to_intent(screen: str) -> str:
    mapping = {
        "instant_payment": "payment_create",
        "payment_order": "payment_order",
        "statement": "statements_filter",
        "account_requisites": "requisites",
        "account_view": "account_view",
        "employees": "employees",
        "service_package_form": "service_package",
    }
    return mapping.get(screen, screen)
