"""Unit tests for ChatOrchestrator.plan() return type."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Heavy optional deps are mocked so orchestrator can load in CI/dev without full stack.
for _mod in ("sentence_transformers", "qdrant_client", "chonkie", "rank_bm25"):
    sys.modules.setdefault(_mod, MagicMock())

from app.intent.models import OrchestratorResult
from app.intent.router import route_message
from app.services.conversation_slots import ConversationSlots
from app.services.orchestrator import ChatOrchestrator
from app.storage.database import DEFAULT_USER_ID, Database


class OrchestratorPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        cls.db = Database(db_path=Path(cls.tmp.name))
        cls.orchestrator = ChatOrchestrator(cls.db)
        cls.user_id = DEFAULT_USER_ID

    @classmethod
    def tearDownClass(cls) -> None:
        del cls.db
        try:
            Path(cls.tmp.name).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_plan_returns_orchestrator_result_tuple(self) -> None:
        result = self.orchestrator.plan(
            "остаток по счёту …1111",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        plan, slots = result
        self.assertIsInstance(plan, OrchestratorResult)
        self.assertIsInstance(slots, ConversationSlots)
        self.assertIsInstance(plan.actions, list)
        self.assertTrue(plan.text or plan.use_llm or plan.actions)

    def test_balance_returns_text_and_view_button(self) -> None:
        plan, _ = self.orchestrator.plan(
            "остаток по счёту …1111",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertFalse(plan.use_llm)
        self.assertIn("1111", plan.text.lower())
        navigate = [a for a in plan.actions if a.get("type") == "navigate"]
        self.assertTrue(navigate)
        self.assertEqual(navigate[0].get("label"), "Просмотреть")

    def test_statement_ambiguous_account_asks_clarification(self) -> None:
        plan, slots = self.orchestrator.plan(
            "сформируй выписку за вчера",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertIn("счёт", plan.text.lower())
        self.assertFalse(any(a.get("type") == "navigate" for a in plan.actions))
        self.assertTrue(slots.pending_account or "account" not in slots.form_data)

    def test_lost_ecp_uses_llm_not_payment(self) -> None:
        plan, _ = self.orchestrator.plan(
            "Я потерял ЭЦП",
            self.user_id,
            "rag context",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertTrue(plan.use_llm)
        self.assertFalse(any(a.get("type") == "navigate" for a in plan.actions))

    def test_help_lost_ecp_uses_llm(self) -> None:
        plan, _ = self.orchestrator.plan(
            "Помоги, потерял ЭЦП",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertTrue(plan.use_llm)

    def test_ecp_cost_uses_llm_not_balance(self) -> None:
        plan, slots = self.orchestrator.plan(
            "Сколько стоит восстановление ЭЦП",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertTrue(plan.use_llm)
        self.assertNotEqual(slots.active_intent, "account_balance")

    def test_card_types_question_uses_llm(self) -> None:
        plan, _ = self.orchestrator.plan(
            "Какие бывают карты?",
            self.user_id,
            "cards kb",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertTrue(plan.use_llm)

    def test_payment_slots_reset_on_ecp_topic(self) -> None:
        slots = ConversationSlots(
            active_intent="payment_create",
            target_screen="instant_payment",
            form_data={"amount": "500 BYN", "recipient": "Иванов"},
        )
        plan, new_slots = self.orchestrator.plan(
            "потерял эцп",
            self.user_id,
            "",
            history=[],
            slots=slots,
        )
        self.assertTrue(plan.use_llm)
        self.assertIsNone(new_slots.active_intent)
        self.assertFalse(new_slots.form_data)

    def test_account_balance_on_account(self) -> None:
        plan, _ = self.orchestrator.plan(
            "Сколько на счёте",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertFalse(plan.use_llm)
        self.assertIn("сч", plan.text.lower())

    def test_create_payment_navigates_with_prefill(self) -> None:
        plan, slots = self.orchestrator.plan(
            "Создай платёж 500 BYN Иванову",
            self.user_id,
            "",
            history=[],
            slots=ConversationSlots(),
        )
        self.assertFalse(plan.use_llm)
        navigate = [a for a in plan.actions if a.get("type") == "navigate"]
        self.assertTrue(navigate or slots.form_data)

    def test_router_operator_escalates(self) -> None:
        decision = route_message("Позови оператора")
        self.assertEqual(decision.mode, "ESCALATE")

    def test_router_aggressive_escalates(self) -> None:
        decision = route_message("Ты идиот")
        self.assertEqual(decision.mode, "ESCALATE")


if __name__ == "__main__":
    unittest.main()
