"""Unit tests for conversation slots."""

import unittest

from app.intent.form_hints import extract_payment_hints, merge_hints
from app.services.conversation_slots import (
    ConversationSlots,
    is_follow_up_message,
    merge_message_hints,
    payment_ready,
)


class ConversationSlotsTests(unittest.TestCase):
    def test_merge_form_data_across_turns(self) -> None:
        slots = ConversationSlots(active_intent="payment_create", target_screen="instant_payment")
        slots.form_data = merge_hints(slots.form_data, extract_payment_hints("200 рублей Алексею"))
        slots.form_data = merge_hints(slots.form_data, extract_payment_hints("на счёт AAB123"))
        self.assertEqual(slots.form_data.get("amount"), "200 RUB")
        self.assertEqual(slots.form_data.get("recipient"), "AAB123")

    def test_payment_ready(self) -> None:
        slots = ConversationSlots(active_intent="payment_create", form_data={"amount": "200 RUB"})
        self.assertFalse(payment_ready(slots))
        slots.form_data["recipient"] = "Алексей"
        self.assertTrue(payment_ready(slots))

    def test_follow_up_detection(self) -> None:
        slots = ConversationSlots(active_intent="payment_create")
        self.assertTrue(is_follow_up_message("за вчера", slots))
        self.assertTrue(is_follow_up_message("4000 рублей", slots))

    def test_merge_message_hints_from_history(self) -> None:
        slots = ConversationSlots()
        history = [
            {"role": "user", "content": "200 рублей Алексею"},
            {"role": "assistant", "content": "Укажите получателя"},
        ]
        slots = merge_message_hints(slots, "на AAB123", "instant_payment", history)
        self.assertEqual(slots.form_data.get("amount"), "200 RUB")
        self.assertEqual(slots.form_data.get("recipient"), "AAB123")


if __name__ == "__main__":
    unittest.main()
