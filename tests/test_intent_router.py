"""Unit tests for intent router."""

import sys
import unittest
from unittest.mock import MagicMock

for _mod in ("sentence_transformers", "qdrant_client", "chonkie", "rank_bm25"):
    sys.modules.setdefault(_mod, MagicMock())

from app.intent.router import route_message
from app.services.conversation_slots import ConversationSlots


class IntentRouterTests(unittest.TestCase):
    def _route(self, message: str, slots: ConversationSlots | None = None):
        return route_message(message, history=[], slots=slots or ConversationSlots())

    def test_lost_ecp_is_faq(self) -> None:
        decision = self._route("Я потерял ЭЦП")
        self.assertEqual(decision.mode, "FAQ")
        self.assertNotIn("payment", decision.reason)

    def test_help_lost_ecp_is_faq_not_payment(self) -> None:
        decision = self._route("Помоги, потерял ЭЦП")
        self.assertEqual(decision.mode, "FAQ")
        if decision.intents:
            self.assertNotEqual(decision.intents[0].intent_id, "nav_instant_payment_action")

    def test_ecp_cost_is_faq_not_balance(self) -> None:
        decision = self._route("Сколько стоит восстановление ЭЦП")
        self.assertEqual(decision.mode, "FAQ")
        if decision.intents:
            self.assertNotEqual(decision.intents[0].intent_id, "account_balance")

    def test_card_types_question_is_faq(self) -> None:
        decision = self._route("Какие бывают карты?")
        self.assertEqual(decision.mode, "FAQ")

    def test_payment_slots_topic_shift_to_ecp(self) -> None:
        slots = ConversationSlots(
            active_intent="payment_create",
            target_screen="instant_payment",
            form_data={"amount": "500 BYN", "recipient": "Иванов"},
        )
        decision = self._route("потерял эцп", slots=slots)
        self.assertEqual(decision.mode, "FAQ")
        self.assertTrue(decision.reset_slots)

    def test_account_balance_is_tool(self) -> None:
        decision = self._route("Сколько на счёте")
        self.assertEqual(decision.mode, "TOOL")
        self.assertTrue(decision.intents)
        self.assertEqual(decision.intents[0].intent_id, "account_balance")

    def test_create_payment_is_tool_navigate(self) -> None:
        decision = self._route("Создай платёж 500 BYN Иванову")
        self.assertEqual(decision.mode, "TOOL")
        self.assertTrue(decision.intents)
        self.assertEqual(decision.intents[0].response_mode.value, "navigate")

    def test_operator_request_escalates(self) -> None:
        decision = self._route("Позови оператора")
        self.assertEqual(decision.mode, "ESCALATE")

    def test_aggressive_message_escalates(self) -> None:
        decision = self._route("Ты идиот")
        self.assertEqual(decision.mode, "ESCALATE")


if __name__ == "__main__":
    unittest.main()
