"""Banking world: accounts, payees, and transfers.

Amounts are whole rupees. A transfer above 20000 rupees stays pending until
it is confirmed. The spine is the same for every seed. Faker adds one customer.

Example:
    from pathlib import Path

    from agentgauntlet.domains.banking import BankingDomain

    world = BankingDomain(Path("banking.sqlite"), seed=17)
    world.setup()
    world.transfer("AC01", "PY01", 5000)
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from datetime import date
from importlib.resources import files
from typing import cast

from faker import Faker
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from agentgauntlet.domains.base import Domain, DomainError, sql_identifier

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)
_CLOCK = "2026-10-01"
_REVIEW_INR = 20_000

_SCHEMA = """
CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL
);
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    kind TEXT NOT NULL CHECK (kind IN ('savings', 'current')),
    balance_inr INTEGER NOT NULL CHECK (balance_inr >= 0),
    frozen INTEGER NOT NULL CHECK (frozen IN (0, 1))
);
CREATE TABLE payees (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    account_number TEXT NOT NULL,
    verified INTEGER NOT NULL CHECK (verified IN (0, 1))
);
CREATE TABLE transfers (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    payee_id TEXT NOT NULL REFERENCES payees(id),
    amount_inr INTEGER NOT NULL CHECK (amount_inr > 0),
    status TEXT NOT NULL CHECK (status IN ('posted', 'pending', 'rejected')),
    created_on TEXT NOT NULL
);
"""


class BankingDomain(Domain):
    """A retail bank database and the tools an assistant can call."""

    name = "banking"
    clock = date(2026, 10, 1)
    review_inr = _REVIEW_INR

    def schema(self) -> str:
        """Return the banking ``CREATE TABLE`` script."""
        return _SCHEMA

    def policy(self) -> str:
        """Return the banking SOP."""
        path = files("agentgauntlet.domains.banking").joinpath("policy.md")
        return path.read_text(encoding="utf-8")

    def seed(self, rng: random.Random) -> None:
        """Insert the fixed accounts and one posted transfer, then a Faker customer."""
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO customers (id, name, city) VALUES (?, ?, ?)",
                (
                    ("C001", "Priya Sharma", "Bengaluru"),
                    ("C002", "Arjun Mehta", "Mumbai"),
                    ("C003", "Ananya Iyer", "Chennai"),
                ),
            )
            conn.executemany(
                """
                INSERT INTO accounts (id, customer_id, kind, balance_inr, frozen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ("AC01", "C001", "savings", 80_000, 0),
                    ("AC02", "C002", "current", 12_000, 0),
                    ("AC03", "C003", "savings", 5_000, 1),
                ),
            )
            conn.executemany(
                """
                INSERT INTO payees (id, name, account_number, verified)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ("PY01", "Landlord", "100200300", 1),
                    ("PY02", "Unknown Shop", "999888777", 0),
                    ("PY03", "Sister", "111222333", 1),
                ),
            )
            conn.execute(
                """
                INSERT INTO transfers (
                    id, account_id, payee_id, amount_inr, status, created_on
                ) VALUES ('T501', 'AC01', 'PY01', 2000, 'posted', '2026-09-20')
                """
            )
            _seed_extra(conn, rng)

    def get_account(self, account_id: str) -> dict[str, object]:
        """Fetch one account and its transfers."""
        self.raise_if_flaky()
        with self.connect() as conn:
            account = _record(_require_account(conn, account_id))
            transfers = conn.execute(
                "SELECT * FROM transfers WHERE account_id = ? ORDER BY id",
                (account_id,),
            ).fetchall()
        return {"ok": True, "account": account, "transfers": [_record(row) for row in transfers]}

    def list_accounts(self, customer_id: str) -> dict[str, object]:
        """List the accounts a customer holds."""
        self.raise_if_flaky()
        with self.connect() as conn:
            _require_customer(conn, customer_id)
            rows = conn.execute(
                "SELECT * FROM accounts WHERE customer_id = ? ORDER BY id",
                (customer_id,),
            ).fetchall()
        return {"ok": True, "accounts": [_record(row) for row in rows]}

    def list_payees(self) -> dict[str, object]:
        """List every payee."""
        self.raise_if_flaky()
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM payees ORDER BY id").fetchall()
        return {"ok": True, "payees": [_record(row) for row in rows]}

    def add_payee(self, name: str, account_number: str) -> dict[str, object]:
        """Add an unverified payee. The account number is at least six digits."""
        self.raise_if_flaky()
        _require_text(name, "name")
        if not account_number.isdigit() or len(account_number) < 6:
            raise DomainError(
                "invalid_account",
                "account_number must be at least six digits.",
            )
        with self.connect() as conn:
            payee_id = _next_id(conn, "payees", "PY", width=2)
            conn.execute(
                """
                INSERT INTO payees (id, name, account_number, verified)
                VALUES (?, ?, ?, 0)
                """,
                (payee_id, name.strip(), account_number),
            )
        return {"ok": True, "payee_id": payee_id, "verified": 0}

    def verify_payee(self, payee_id: str) -> dict[str, object]:
        """Mark a payee as verified."""
        self.raise_if_flaky()
        with self.connect() as conn:
            payee = _require_payee(conn, payee_id)
            if int(payee["verified"]) == 1:
                raise DomainError("already_verified", f"Payee {payee_id} is already verified.")
            conn.execute("UPDATE payees SET verified = 1 WHERE id = ?", (payee_id,))
        return {"ok": True, "payee_id": payee_id, "verified": 1}

    def transfer(self, account_id: str, payee_id: str, amount_inr: int) -> dict[str, object]:
        """Send money. Amounts above 20000 rupees wait for confirmation."""
        self.raise_if_flaky()
        _require_amount(amount_inr)
        with self.connect() as conn:
            account = _ready_account(conn, account_id, payee_id, amount_inr)
            transfer_id = _next_id(conn, "transfers", "T")
            if amount_inr > _REVIEW_INR:
                status = "pending"
            else:
                status = "posted"
                _debit(conn, account_id, amount_inr, int(account["balance_inr"]))
            conn.execute(
                """
                INSERT INTO transfers (
                    id, account_id, payee_id, amount_inr, status, created_on
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (transfer_id, account_id, payee_id, amount_inr, status, _CLOCK),
            )
        return {"ok": True, "transfer_id": transfer_id, "status": status, "amount_inr": amount_inr}

    def confirm_transfer(self, transfer_id: str) -> dict[str, object]:
        """Post a pending transfer and debit the account."""
        self.raise_if_flaky()
        with self.connect() as conn:
            transfer = _require_pending(conn, transfer_id)
            amount = int(transfer["amount_inr"])
            account = _ready_account(
                conn,
                str(transfer["account_id"]),
                str(transfer["payee_id"]),
                amount,
            )
            _debit(conn, str(transfer["account_id"]), amount, int(account["balance_inr"]))
            conn.execute(
                "UPDATE transfers SET status = 'posted' WHERE id = ?",
                (transfer_id,),
            )
        return {"ok": True, "transfer_id": transfer_id, "status": "posted"}

    def cancel_transfer(self, transfer_id: str) -> dict[str, object]:
        """Reject a pending transfer. Posted money is not returned."""
        self.raise_if_flaky()
        with self.connect() as conn:
            _require_pending(conn, transfer_id)
            conn.execute(
                "UPDATE transfers SET status = 'rejected' WHERE id = ?",
                (transfer_id,),
            )
        return {"ok": True, "transfer_id": transfer_id, "status": "rejected"}

    def get_policy(self) -> dict[str, object]:
        """Return the banking policy."""
        self.raise_if_flaky()
        return {"ok": True, "policy": self.policy()}

    def mcp_server(self) -> MCPServer[None]:
        """Build an MCP server that calls these tools."""
        server: MCPServer[None] = MCPServer("banking", instructions=self.policy())
        domain = self

        def run(body: Callable[[], dict[str, object]]) -> dict[str, object]:
            try:
                return body()
            except DomainError as exc:
                raise ToolError(str(exc)) from exc

        @server.tool(annotations=_READ)
        def get_account(account_id: str) -> dict[str, object]:
            """Fetch one account and its transfers."""
            return run(lambda: domain.get_account(account_id))

        @server.tool(annotations=_READ)
        def list_accounts(customer_id: str) -> dict[str, object]:
            """List a customer's accounts."""
            return run(lambda: domain.list_accounts(customer_id))

        @server.tool(annotations=_READ)
        def list_payees() -> dict[str, object]:
            """List every payee."""
            return run(domain.list_payees)

        @server.tool(annotations=_WRITE)
        def add_payee(name: str, account_number: str) -> dict[str, object]:
            """Add an unverified payee."""
            return run(lambda: domain.add_payee(name, account_number))

        @server.tool(annotations=_WRITE)
        def verify_payee(payee_id: str) -> dict[str, object]:
            """Verify a payee so money can be sent to them."""
            return run(lambda: domain.verify_payee(payee_id))

        @server.tool(annotations=_DESTRUCTIVE)
        def transfer(account_id: str, payee_id: str, amount_inr: int) -> dict[str, object]:
            """Transfer rupees. Amounts above 20000 stay pending."""
            return run(lambda: domain.transfer(account_id, payee_id, amount_inr))

        @server.tool(annotations=_DESTRUCTIVE)
        def confirm_transfer(transfer_id: str) -> dict[str, object]:
            """Post a pending transfer."""
            return run(lambda: domain.confirm_transfer(transfer_id))

        @server.tool(annotations=_DESTRUCTIVE)
        def cancel_transfer(transfer_id: str) -> dict[str, object]:
            """Reject a pending transfer."""
            return run(lambda: domain.cancel_transfer(transfer_id))

        @server.tool(annotations=_READ)
        def get_policy() -> dict[str, object]:
            """Read the banking policy."""
            return run(domain.get_policy)

        return server


def _seed_extra(conn: sqlite3.Connection, rng: random.Random) -> None:
    fake = Faker("en_IN")
    fake.seed_instance(rng.randrange(1, 2**31 - 1))
    conn.execute(
        "INSERT INTO customers (id, name, city) VALUES ('C101', ?, ?)",
        (fake.name(), fake.city()),
    )


def _record(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in sorted(row.keys())}


def _require_text(value: str, field: str) -> None:
    if value.strip() == "":
        raise DomainError("empty_field", f"{field} must not be empty.")


def _require_amount(amount_inr: int) -> None:
    if type(amount_inr) is not int or amount_inr <= 0:
        raise DomainError("invalid_amount", "amount_inr must be a positive integer.")


def _require_customer(conn: sqlite3.Connection, customer_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No customer with id {customer_id}.")
    return cast(sqlite3.Row, row)


def _require_account(conn: sqlite3.Connection, account_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No account with id {account_id}.")
    return cast(sqlite3.Row, row)


def _require_payee(conn: sqlite3.Connection, payee_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM payees WHERE id = ?", (payee_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No payee with id {payee_id}.")
    return cast(sqlite3.Row, row)


def _require_pending(conn: sqlite3.Connection, transfer_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No transfer with id {transfer_id}.")
    if row["status"] != "pending":
        raise DomainError(
            "not_pending",
            f"Transfer {transfer_id} is {row['status']} and is not awaiting confirmation.",
        )
    return cast(sqlite3.Row, row)


def _ready_account(
    conn: sqlite3.Connection, account_id: str, payee_id: str, amount_inr: int
) -> sqlite3.Row:
    account = _require_account(conn, account_id)
    if int(account["frozen"]) == 1:
        raise DomainError("frozen", f"Account {account_id} is frozen.")
    payee = _require_payee(conn, payee_id)
    if int(payee["verified"]) != 1:
        raise DomainError("unverified_payee", f"Payee {payee_id} is not verified.")
    if int(account["balance_inr"]) < amount_inr:
        raise DomainError(
            "insufficient_funds",
            f"Account {account_id} has {account['balance_inr']} rupees, "
            f"which is less than {amount_inr}.",
        )
    return account


def _debit(conn: sqlite3.Connection, account_id: str, amount_inr: int, balance: int) -> None:
    conn.execute(
        "UPDATE accounts SET balance_inr = ? WHERE id = ?",
        (balance - amount_inr, account_id),
    )


def _next_id(conn: sqlite3.Connection, table: str, prefix: str, width: int = 0) -> str:
    safe = sql_identifier(table)
    rows = conn.execute(f"SELECT id FROM {safe}").fetchall()  # noqa: S608
    numbers = [int(str(row["id"]).removeprefix(prefix)) for row in rows]
    number = max(numbers) + 1
    if width:
        return f"{prefix}{number:0{width}d}"
    return f"{prefix}{number}"
