"""Unit tests for resolve_account."""

import tempfile
import unittest
from pathlib import Path

from app.intent.text_utils import resolve_account
from app.storage.database import DEFAULT_USER_ID, Database


class ResolveAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        cls.db = Database(db_path=Path(cls.tmp.name))
        cls.user_id = DEFAULT_USER_ID

    @classmethod
    def tearDownClass(cls) -> None:
        del cls.db
        try:
            Path(cls.tmp.name).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_resolve_by_suffix_1111(self) -> None:
        result = resolve_account(self.user_id, "остаток по счёту …1111", [], self.db)
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "2")

    def test_resolve_by_suffix_2222(self) -> None:
        result = resolve_account(self.user_id, "счёт 2222", [], self.db)
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "3")

    def test_resolve_by_iban(self) -> None:
        result = resolve_account(
            self.user_id,
            "BY15 BPSB 3612 0000 0000 0933 1111",
            [],
            self.db,
        )
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "2")

    def test_resolve_by_russian_rubles_description(self) -> None:
        result = resolve_account(self.user_id, "реквизиты российские рубли", [], self.db)
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "2")

    def test_resolve_no_info_account(self) -> None:
        result = resolve_account(self.user_id, "счёт без баланса", [], self.db)
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "3")

    def test_resolve_special_account(self) -> None:
        result = resolve_account(self.user_id, "специальный счёт", [], self.db)
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "4")

    def test_resolve_not_found_suffix(self) -> None:
        result = resolve_account(self.user_id, "счёт 9999", [], self.db)
        self.assertEqual(result.status, "not_found")

    def test_resolve_from_history(self) -> None:
        history = [{"role": "user", "content": "выписка по счёту 1111"}]
        result = resolve_account(self.user_id, "за вчера", history, self.db)
        self.assertEqual(result.status, "found")
        assert result.account is not None
        self.assertEqual(result.account["id"], "2")


if __name__ == "__main__":
    unittest.main()
