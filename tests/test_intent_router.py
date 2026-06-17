"""Unit tests for intent router."""

import sys
import unittest
from unittest.mock import MagicMock

for _mod in ("sentence_transformers", "qdrant_client", "chonkie", "rank_bm25"):
    sys.modules.setdefault(_mod, MagicMock())

from app.intent.classifier import classify
from app.intent.router import route_message
from app.services.conversation_slots import ConversationSlots, is_correction_message, merge_message_hints


class IntentRouterTests(unittest.TestCase):
    def _route(self, message: str, slots: ConversationSlots | None = None, strikes: int = 0):
        return route_message(message, history=[], slots=slots or ConversationSlots(), aggression_strikes=strikes)

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

    def test_user_cards_is_tool(self) -> None:
        decision = self._route("Какие карты у меня есть?")
        self.assertEqual(decision.mode, "TOOL")
        self.assertTrue(decision.intents)
        self.assertEqual(decision.intents[0].intent_id, "list_user_cards")

    def test_active_cards_is_tool(self) -> None:
        decision = self._route("Есть активные карты?")
        self.assertEqual(decision.mode, "TOOL")
        self.assertEqual(decision.intents[0].intent_id, "list_user_cards")

    def test_nav_cards_screen(self) -> None:
        decision = self._route("Можешь перейти на экран с картами?")
        self.assertEqual(decision.mode, "TOOL")
        self.assertEqual(decision.intents[0].intent_id, "nav_cards_screen")

    def test_correction_overwrites_recipient(self) -> None:
        self.assertTrue(is_correction_message("Нет, получатель ABC333"))
        slots = ConversationSlots(
            active_intent="payment_create",
            target_screen="instant_payment",
            form_data={"recipient": "За", "amount": "100 RUB"},
        )
        slots = merge_message_hints(slots, "Нет, получатель ABC333", "instant_payment")
        self.assertEqual(slots.form_data.get("recipient"), "ABC333")

    def test_block_card_not_cancel(self) -> None:
        decision = self._route("Мне нужно заблокировать карту")
        self.assertNotEqual(decision.mode, "RESET_SLOTS")
        self.assertEqual(decision.mode, "TOOL")
        self.assertEqual(decision.intents[0].intent_id, "block_card")

    def test_transfer_to_employee_escalates(self) -> None:
        decision = self._route("переведи на сотрудника")
        self.assertEqual(decision.mode, "ESCALATE")

    def test_sexual_aggression_warns_not_payment(self) -> None:
        decision = self._route("соси член")
        self.assertIn(decision.mode, ("AGGRESSION", "ESCALATE"))
        self.assertNotEqual(decision.mode, "TOOL")

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

    def test_aggressive_message_warns(self) -> None:
        decision = self._route("Ты идиот")
        self.assertEqual(decision.mode, "AGGRESSION")

    def test_repeat_aggression_escalates(self) -> None:
        decision = self._route("Ты идиот", strikes=1)
        self.assertEqual(decision.mode, "ESCALATE")


if __name__ == "__main__":
    unittest.main()
