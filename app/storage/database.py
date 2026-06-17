"""SQLite-хранилище: история чата, черновики, эскалации, банковские данные."""

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import DB_PATH, STORAGE_DIR

DEFAULT_USER_ID = "demo_user"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    escalated INTEGER DEFAULT 0,
                    operator_active INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );

                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    draft_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    route TEXT NOT NULL,
                    form_data TEXT DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    avatar TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    number TEXT NOT NULL,
                    name TEXT NOT NULL,
                    balance TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    hidden INTEGER DEFAULT 0,
                    no_info INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS employees (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    first_name TEXT NOT NULL,
                    middle_name TEXT DEFAULT '',
                    position TEXT DEFAULT '',
                    account TEXT DEFAULT '',
                    phone TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    holder TEXT DEFAULT '',
                    account_number TEXT DEFAULT '',
                    expiry TEXT DEFAULT '',
                    doc_date TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS statement_transactions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    tx_date TEXT NOT NULL,
                    description TEXT NOT NULL,
                    debit TEXT DEFAULT '',
                    credit TEXT DEFAULT '',
                    balance TEXT NOT NULL
                );
            """)
            self._seed_banking_data(conn)
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "metadata" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN metadata TEXT DEFAULT '{}'")

    def get_conversation_slots(self, conversation_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not row:
                return {}
            meta = json.loads(row["metadata"] or "{}")
            return meta.get("slots", {})

    def set_conversation_slots(self, conversation_id: str, slots: dict) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            meta = json.loads(row["metadata"] or "{}") if row else {}
            meta["slots"] = slots
            conn.execute(
                "UPDATE conversations SET metadata = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), _now(), conversation_id),
            )

    def get_aggression_strikes(self, conversation_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not row:
                return 0
            meta = json.loads(row["metadata"] or "{}")
            return int(meta.get("aggression_strikes", 0))

    def set_aggression_strikes(self, conversation_id: str, strikes: int) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            meta = json.loads(row["metadata"] or "{}") if row else {}
            meta["aggression_strikes"] = strikes
            conn.execute(
                "UPDATE conversations SET metadata = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), _now(), conversation_id),
            )

    # --- Conversations ---

    def get_or_create_conversation(self, user_id: str, conversation_id: str | None) -> str:
        with self._connect() as conn:
            if conversation_id:
                row = conn.execute(
                    "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
                    (conversation_id, user_id),
                ).fetchone()
                if row:
                    return row["id"]

            new_id = str(uuid.uuid4())
            now = _now()
            conn.execute(
                "INSERT INTO conversations (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (new_id, user_id, now, now),
            )
            return new_id

    def get_messages(self, conversation_id: str, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, role, content, metadata, created_at
                   FROM messages WHERE conversation_id = ?
                   ORDER BY created_at ASC LIMIT ?""",
                (conversation_id, limit),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), conversation_id, role, content, json.dumps(metadata or {}), _now()),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now(), conversation_id),
            )

    def escalate_conversation(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET escalated = 1, updated_at = ? WHERE id = ?",
                (_now(), conversation_id),
            )

    def get_escalated_conversations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, created_at, updated_at FROM conversations WHERE escalated = 1 ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Drafts ---

    def upsert_draft(
        self,
        user_id: str,
        draft_type: str,
        title: str,
        route: str,
        form_data: dict,
        draft_id: str | None = None,
    ) -> str:
        draft_id = draft_id or str(uuid.uuid4())
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM drafts WHERE user_id = ? AND draft_type = ?",
                (user_id, draft_type),
            ).fetchone()
            if existing:
                draft_id = existing["id"]
                conn.execute(
                    "UPDATE drafts SET title = ?, route = ?, form_data = ?, updated_at = ? WHERE id = ?",
                    (title, route, json.dumps(form_data), _now(), draft_id),
                )
            else:
                conn.execute(
                    "INSERT INTO drafts (id, user_id, draft_type, title, route, form_data, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (draft_id, user_id, draft_type, title, route, json.dumps(form_data), _now()),
                )
        return draft_id

    def get_drafts(self, user_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, draft_type, title, route, form_data, updated_at FROM drafts WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "draft_type": r["draft_type"],
                    "title": r["title"],
                    "route": r["route"],
                    "form_data": json.loads(r["form_data"]),
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]

    def delete_draft(self, user_id: str, draft_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM drafts WHERE id = ? AND user_id = ?",
                (draft_id, user_id),
            )
            return cur.rowcount > 0

    # --- Operator ---

    def add_operator_message(self, conversation_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO operator_messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), conversation_id, role, content, _now()),
            )

    def get_operator_messages(self, conversation_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM operator_messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def is_escalated(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT escalated FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            return bool(row and row["escalated"])


    def _seed_banking_data(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM accounts").fetchone()
        if row and row["cnt"] > 0:
            return

        conn.execute(
            "INSERT INTO user_profiles (user_id, name, avatar) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, "DEMO ЮРИДИЧЕСКОЕ ЛИЦО", ""),
        )

        accounts = [
            ("1", DEFAULT_USER_ID, "BY15 BPSB 3612 0000 0000 0933 0000", "Текущий счет (расчетный)", "16 780,00", "BYN", "На строительство дороги по договору 4512...", 1, 0),
            ("2", DEFAULT_USER_ID, "BY15 BPSB 3612 0000 0000 0933 1111", "Российские рубли", "12 226 780,00", "RUB", "", 0, 0),
            ("3", DEFAULT_USER_ID, "BY15 BPSB 3612 0000 0000 0933 2222", "Текущий счет (расчетный)", "н/д", "BYN", "", 0, 1),
            ("4", DEFAULT_USER_ID, "BY15 BPSB 3612 0000 0000 0933 3333", "Специальный счет", "1 999 222 999,00", "BYN", "", 1, 0),
        ]
        conn.executemany(
            "INSERT INTO accounts (id, user_id, number, name, balance, currency, description, hidden, no_info) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            accounts,
        )

        employees = [
            ("1", DEFAULT_USER_ID, "РЯЗАНОВ", "АЛЕКСЕЙ", "АЛЕКСЕЕВИЧ", "ДИРЕКТОР", "BY02 BPSB 3014 9087 3456 7890 9087", ""),
            ("2", DEFAULT_USER_ID, "СИДОРОВ", "ПЕТР", "ПЕТРОВИЧ", "", "BY46 BPSB 3034 F250 0586 7859 3300", ""),
            ("3", DEFAULT_USER_ID, "ИВАНОВ", "ВАСИЛИЙ", "ИВАНОВИЧ", "ПАСПОРТ ГРАЖДАНИНА РБ", "", ""),
            ("4", DEFAULT_USER_ID, "ПЕТРОВ", "КОНСТАНТИН", "АЛЕКСАНДРОВИЧ", "БУХГАЛТЕР", "BY12 BPSB 3012 1111 2222 3333 4444", ""),
            ("5", DEFAULT_USER_ID, "ВАСИЛЬЕВ", "СЕРГЕЙ", "НИКОЛАЕВИЧ", "", "", ""),
            ("6", DEFAULT_USER_ID, "МИХАЙЛОВ", "ДМИТРИЙ", "ОЛЕГОВИЧ", "МЕНЕДЖЕР", "BY33 BPSB 3015 5555 6666 7777 8888", ""),
        ]
        conn.executemany(
            "INSERT INTO employees (id, user_id, last_name, first_name, middle_name, position, account, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            employees,
        )

        cards = [
            ("4521", DEFAULT_USER_ID, "**** 4521", "Бизнес-карта", "active", "DEMO IURIDICHESKOE LITCO", "BY51 BPSB 3012 2222 2222 2933 2222", "12/28", "13.06.2026"),
            ("4522", DEFAULT_USER_ID, "**** 4522", "Корпоративная карта", "blocked", "DEMO IURIDICHESKOE LITCO", "BY51 BPSB 3012 2222 2222 2933 2222", "12/28", "10.06.2026"),
        ]
        conn.executemany(
            "INSERT INTO cards (id, user_id, label, name, status, holder, account_number, expiry, doc_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            cards,
        )

        today = date.today()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=5)
        month_ago = today - timedelta(days=20)

        transactions = [
            (str(uuid.uuid4()), DEFAULT_USER_ID, "1", today.isoformat(), "Поступление от контрагента ООО «Строй»", "", "5 000,00", "21 780,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "1", today.isoformat(), "Комиссия за обслуживание", "120,00", "", "21 660,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "1", yesterday.isoformat(), "Оплата поставщику", "4 880,00", "", "16 780,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "1", yesterday.isoformat(), "Возврат переплаты", "", "1 200,00", "18 980,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "1", week_ago.isoformat(), "Зарплатный проект", "85 000,00", "", "17 780,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "1", month_ago.isoformat(), "Поступление по договору №4512", "", "100 000,00", "102 780,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "2", today.isoformat(), "Конвертация RUB → BYN", "50 000,00", "", "12 176 780,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "2", yesterday.isoformat(), "Поступление от партнёра", "", "250 000,00", "12 226 780,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "4", today.isoformat(), "Списание по спецсчёту", "1 000,00", "", "1 999 221 999,00"),
            (str(uuid.uuid4()), DEFAULT_USER_ID, "4", week_ago.isoformat(), "Пополнение спецсчёта", "", "500 000,00", "1 999 222 999,00"),
        ]
        conn.executemany(
            "INSERT INTO statement_transactions (id, user_id, account_id, tx_date, description, debit, credit, balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            transactions,
        )

    def get_profile(self, user_id: str = DEFAULT_USER_ID) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, name, avatar FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return {"user_id": user_id, "name": "DEMO ЮРИДИЧЕСКОЕ ЛИЦО", "avatar": ""}
            return dict(row)

    def get_accounts(self, user_id: str = DEFAULT_USER_ID) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, number, name, balance, currency, description, hidden, no_info FROM accounts WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "number": r["number"],
                    "name": r["name"],
                    "balance": r["balance"],
                    "currency": r["currency"],
                    "currencyCode": r["currency"],
                    "description": r["description"] or None,
                    "hidden": bool(r["hidden"]),
                    "noInfo": bool(r["no_info"]),
                }
                for r in rows
            ]

    def get_total_balance_byn(self, user_id: str = DEFAULT_USER_ID) -> str:
        accounts = self.get_accounts(user_id)
        total = 0.0
        for a in accounts:
            if a["currency"] != "BYN" or a["noInfo"]:
                continue
            bal = a["balance"].replace(" ", "").replace(",", ".")
            if bal == "н/д":
                continue
            try:
                total += float(bal)
            except ValueError:
                pass
        formatted = f"{total:,.2f}".replace(",", " ").replace(".", ",")
        return f"{formatted} BYN"

    def get_employees(self, user_id: str = DEFAULT_USER_ID) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, last_name, first_name, middle_name, position, account, phone FROM employees WHERE user_id = ? ORDER BY last_name, first_name",
                (user_id,),
            ).fetchall()
            result = []
            for r in rows:
                parts = [r["last_name"], r["first_name"], r["middle_name"]]
                full_name = " ".join(p for p in parts if p)
                initials = (r["last_name"][:1] + r["first_name"][:1]).upper() if r["last_name"] and r["first_name"] else "??"
                result.append({
                    "id": r["id"],
                    "lastName": r["last_name"],
                    "firstName": r["first_name"],
                    "middleName": r["middle_name"],
                    "position": r["position"],
                    "account": r["account"],
                    "phone": r["phone"],
                    "fullName": full_name,
                    "initials": initials,
                })
            return result

    def create_employee(self, user_id: str, data: dict) -> dict:
        emp_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO employees (id, user_id, last_name, first_name, middle_name, position, account, phone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    emp_id,
                    user_id,
                    data.get("lastName", ""),
                    data.get("firstName", ""),
                    data.get("middleName", ""),
                    data.get("position", ""),
                    data.get("account", ""),
                    data.get("phone", ""),
                ),
            )
        employees = self.get_employees(user_id)
        return next(e for e in employees if e["id"] == emp_id)

    def delete_employee(self, user_id: str, employee_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM employees WHERE id = ? AND user_id = ?",
                (employee_id, user_id),
            )
            return cur.rowcount > 0

    def get_cards(self, user_id: str = DEFAULT_USER_ID) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, label, name, status, holder, account_number, expiry, doc_date FROM cards WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_card(self, user_id: str, card_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, label, name, status, holder, account_number, expiry, doc_date FROM cards WHERE user_id = ? AND id = ?",
                (user_id, card_id),
            ).fetchone()
            return dict(row) if row else None

    def update_card_status(self, user_id: str, card_id: str, status: str) -> dict | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE cards SET status = ? WHERE user_id = ? AND id = ?",
                (status, user_id, card_id),
            )
        return self.get_card(user_id, card_id)

    def get_statement_reference(self) -> dict:
        return {
            "tabs": ["ПО СЧЕТАМ", "ПО КОРПОКАРТАМ", "РЕЕСТР ОСТАТКОВ", "ОТЧЕТ", "ВЫПИСКА ПО РАСПИСАНИЮ"],
            "periods": [
                {"key": "today", "label": "Сегодня"},
                {"key": "yesterday", "label": "Вчера"},
                {"key": "last_week", "label": "Прошлая неделя"},
                {"key": "last_month", "label": "Прошлый месяц"},
                {"key": "last_quarter", "label": "Прошлый квартал"},
            ],
        }

    def _period_range(self, period: str) -> tuple[date, date]:
        today = date.today()
        if period == "today":
            return today, today
        if period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if period == "last_week":
            return today - timedelta(days=7), today
        if period == "last_month":
            return today - timedelta(days=30), today
        if period == "last_quarter":
            return today - timedelta(days=90), today
        return today, today

    def generate_statement(
        self,
        user_id: str,
        account: str = "all",
        period: str = "today",
        zero_turnover: bool = False,
        daily: bool = False,
        revaluation: bool = False,
    ) -> dict:
        start, end = self._period_range(period)
        accounts = self.get_accounts(user_id)
        if account != "all":
            accounts = [a for a in accounts if a["id"] == account or a["number"] == account]
        account_ids = [a["id"] for a in accounts]

        with self._connect() as conn:
            placeholders = ",".join("?" * len(account_ids)) if account_ids else "?"
            params: list[Any] = [user_id] + (account_ids if account_ids else [""])
            rows = conn.execute(
                f"""SELECT account_id, tx_date, description, debit, credit, balance
                    FROM statement_transactions
                    WHERE user_id = ? AND account_id IN ({placeholders})
                    AND tx_date >= ? AND tx_date <= ?
                    ORDER BY tx_date ASC, rowid ASC""",
                params + [start.isoformat(), end.isoformat()],
            ).fetchall()

        transactions = [dict(r) for r in rows]
        account_map = {a["id"]: a for a in accounts}

        if not zero_turnover and daily:
            by_date: dict[str, list] = {}
            for tx in transactions:
                by_date.setdefault(tx["tx_date"], []).append(tx)
            transactions = []
            for d in sorted(by_date.keys()):
                day_txs = by_date[d]
                transactions.extend(day_txs)

        result_txs = []
        for tx in transactions:
            acc = account_map.get(tx["account_id"], {})
            result_txs.append({
                "date": tx["tx_date"],
                "accountNumber": acc.get("number", ""),
                "accountName": acc.get("name", ""),
                "description": tx["description"],
                "debit": tx["debit"],
                "credit": tx["credit"],
                "balance": tx["balance"],
            })

        if revaluation and result_txs:
            result_txs.append({
                "date": end.isoformat(),
                "accountNumber": "",
                "accountName": "",
                "description": "Переоценка валютных остатков",
                "debit": "",
                "credit": "0,00",
                "balance": "",
            })

        opening = result_txs[0]["balance"] if result_txs else "0,00"
        closing = result_txs[-1]["balance"] if result_txs else opening
        debit_sum = sum(
            float(t["debit"].replace(" ", "").replace(",", "."))
            for t in result_txs if t["debit"]
        )
        credit_sum = sum(
            float(t["credit"].replace(" ", "").replace(",", "."))
            for t in result_txs if t["credit"]
        )

        def fmt(n: float) -> str:
            return f"{n:,.2f}".replace(",", " ").replace(".", ",")

        period_labels = {p["key"]: p["label"] for p in self.get_statement_reference()["periods"]}

        return {
            "period": period,
            "periodLabel": period_labels.get(period, period),
            "account": account,
            "accounts": [{"id": a["id"], "number": a["number"], "name": a["name"]} for a in accounts],
            "openingBalance": opening,
            "closingBalance": closing,
            "turnoverDebit": fmt(debit_sum),
            "turnoverCredit": fmt(credit_sum),
            "transactionCount": len(result_txs),
            "transactions": result_txs,
            "generatedAt": _now(),
        }

    def get_account_operations_reference(self) -> dict:
        ref = self.get_statement_reference()
        return {
            "periods": [{"key": "all", "label": "За все время"}, *ref["periods"]],
            "operationTypes": [
                {"key": "all", "label": "Все операции"},
                {"key": "credit", "label": "Поступления"},
                {"key": "debit", "label": "Списания"},
            ],
        }

    def get_account_operations(
        self,
        user_id: str,
        account_id: str,
        period: str = "all",
        operation_type: str = "all",
    ) -> dict | None:
        accounts = self.get_accounts(user_id)
        account = next((a for a in accounts if a["id"] == account_id), None)
        if not account:
            return None

        query = """SELECT tx_date, description, debit, credit, balance
                   FROM statement_transactions
                   WHERE user_id = ? AND account_id = ?"""
        params: list[Any] = [user_id, account_id]

        if period != "all":
            start, end = self._period_range(period)
            query += " AND tx_date >= ? AND tx_date <= ?"
            params.extend([start.isoformat(), end.isoformat()])

        query += " ORDER BY tx_date DESC, rowid DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        transactions = []
        for row in rows:
            tx = dict(row)
            if operation_type == "credit" and not tx["credit"]:
                continue
            if operation_type == "debit" and not tx["debit"]:
                continue
            transactions.append({
                "date": tx["tx_date"],
                "description": tx["description"],
                "debit": tx["debit"],
                "credit": tx["credit"],
                "balance": tx["balance"],
            })

        return {
            "account": account,
            "transactions": transactions,
            "count": len(transactions),
        }
