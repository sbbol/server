"""Unit tests for form hint extraction."""

import unittest

from app.intent.form_hints import (
    extract_employee_hints,
    extract_payment_hints,
    extract_service_package_hints,
)
from app.intent.text_utils import is_tariff_faq_question


class FormHintsTests(unittest.TestCase):
    def test_payment_recipient_account_pattern(self) -> None:
        hints = extract_payment_hints("переведи на счёт AAB123")
        self.assertEqual(hints.get("recipient"), "AAB123")

    def test_payment_amount_and_name(self) -> None:
        hints = extract_payment_hints("200 рублей контрагенту Васе")
        self.assertEqual(hints.get("amount"), "200 RUB")
        self.assertEqual(hints.get("recipient"), "Васе")

    def test_payment_dative_name(self) -> None:
        hints = extract_payment_hints("200 руб Алексею")
        self.assertEqual(hints.get("recipient"), "Алексею")
        self.assertEqual(hints.get("amount"), "200 RUB")

    def test_employee_fio_russian_order(self) -> None:
        hints = extract_employee_hints("Лопатов Алексей Дмитриевич, уборщик")
        self.assertEqual(hints.get("lastName"), "Лопатов")
        self.assertEqual(hints.get("firstName"), "Алексей")
        self.assertEqual(hints.get("middleName"), "Дмитриевич")

    def test_employee_email_not_name(self) -> None:
        hints = extract_employee_hints("добавь сотрудника ivan@company.by")
        self.assertEqual(hints.get("email"), "ivan@company.by")
        self.assertNotIn("firstName", hints)

    def test_employee_skips_card_keywords(self) -> None:
        hints = extract_employee_hints("создай бизнес-карту")
        self.assertEqual(hints, {})

    def test_service_package_no_employee_parse(self) -> None:
        hints = extract_service_package_hints("какие тарифы есть")
        self.assertNotIn("firstName", hints)
        self.assertNotIn("lastName", hints)

    def test_tariff_faq_detection(self) -> None:
        self.assertTrue(is_tariff_faq_question("какие тарифы есть"))
        self.assertTrue(is_tariff_faq_question("расскажи про тарифы"))
        self.assertFalse(is_tariff_faq_question("сменить тариф на премиум"))


if __name__ == "__main__":
    unittest.main()
