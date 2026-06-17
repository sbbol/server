"""Unit tests for response builder."""

import unittest

from app.services.response_builder import build_navigate_response, build_prefill_response


class ResponseBuilderTests(unittest.TestCase):
    def test_period_yesterday_localized(self) -> None:
        text = build_prefill_response(
            "Сформировать выписку",
            {"period": "yesterday", "account": "all"},
            "statement",
        )
        self.assertIn("за вчера", text)
        self.assertNotIn("yesterday", text)

    def test_navigate_without_action_no_button_promise(self) -> None:
        text = build_navigate_response(
            "Перейти",
            guided=True,
            screen="statement",
            has_action=False,
        )
        self.assertNotIn("Кнопка", text)
        self.assertNotIn("Нажмите", text)


if __name__ == "__main__":
    unittest.main()
