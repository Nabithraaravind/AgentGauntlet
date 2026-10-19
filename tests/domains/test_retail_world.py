"""Retail world: deterministic seed data and database rules."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from mcp.server import MCPServer

from agentgauntlet.domains.base import sql_identifier
from agentgauntlet.domains.retail import RetailDomain
from agentgauntlet.domains.retail.__main__ import domain_from_args, main

SPINE_ORDER_IDS = ("A1043", "A1044", "A1045", "A1046", "A1047")


def test_same_seed_builds_the_same_world(tmp_path: Path) -> None:
    """Two databases from seed 17 are identical, including Faker rows."""
    first = RetailDomain(tmp_path / "a.sqlite", seed=17)
    second = RetailDomain(tmp_path / "b.sqlite", seed=17)
    first.setup()
    second.setup()
    assert json.dumps(first.snapshot(), sort_keys=True) == json.dumps(
        second.snapshot(), sort_keys=True
    )


def test_spine_orders_exist_in_every_seed(tmp_path: Path) -> None:
    """Named orders stay put. Extra rows are what change between seeds."""
    left = RetailDomain(tmp_path / "left.sqlite", seed=1)
    right = RetailDomain(tmp_path / "right.sqlite", seed=2)
    left.setup()
    right.setup()
    left_ids = {row["id"] for row in left.snapshot()["orders"]}
    right_ids = {row["id"] for row in right.snapshot()["orders"]}
    assert set(SPINE_ORDER_IDS) <= left_ids
    assert set(SPINE_ORDER_IDS) <= right_ids
    assert left.snapshot() != right.snapshot()


def test_snapshot_sorts_rows_and_keys(tmp_path: Path) -> None:
    """The snapshot is stable enough to diff without a custom encoder."""
    domain = RetailDomain(tmp_path / "retail.sqlite", seed=17)
    domain.setup()
    snapshot = domain.snapshot()
    assert list(snapshot) == sorted(snapshot)
    encoded = [json.dumps(row, sort_keys=True) for row in snapshot["products"]]
    assert encoded == sorted(encoded)
    assert list(snapshot["products"][0]) == sorted(snapshot["products"][0])


def test_foreign_keys_reject_an_unknown_customer(tmp_path: Path) -> None:
    """An order must point at a real customer."""
    domain = RetailDomain(tmp_path / "retail.sqlite", seed=17)
    domain.setup()
    with pytest.raises(sqlite3.IntegrityError), domain.connect() as conn:
        conn.execute(
            """
            INSERT INTO orders (
                id, customer_id, status, payment_method, shipping_address,
                shipping_city, ordered_on
            ) VALUES ('A9999', 'NOPE', 'placed', 'upi', '1 Road', 'Pune', '2026-09-01')
            """
        )


def test_setup_replaces_a_previous_database(tmp_path: Path) -> None:
    """A second setup drops writes from the first one."""
    domain = RetailDomain(tmp_path / "retail.sqlite", seed=17)
    domain.setup()
    domain.cancel_order("A1045")
    domain.setup()
    status = next(row["status"] for row in domain.snapshot()["orders"] if row["id"] == "A1045")
    assert status == "placed"


def test_flaky_rate_must_be_a_probability(tmp_path: Path) -> None:
    """Rates outside 0 to 1 are a configuration mistake."""
    with pytest.raises(ValueError, match="flaky_rate"):
        RetailDomain(tmp_path / "retail.sqlite", flaky_rate=1.5)


def test_sql_identifier_rejects_punctuation() -> None:
    """Table names interpolated into snapshot SQL have to be identifiers."""
    assert sql_identifier("orders") == "orders"
    with pytest.raises(ValueError, match="identifier"):
        sql_identifier("orders;drop")


def test_policy_states_the_clock_and_the_window(tmp_path: Path) -> None:
    """The SOP the agent reads names the same date the tools enforce."""
    domain = RetailDomain(tmp_path / "retail.sqlite", seed=17)
    text = domain.policy()
    assert domain.clock.isoformat() in text
    assert str(domain.refund_window_days) in text


def test_domain_from_args_keeps_an_existing_database(tmp_path: Path) -> None:
    """Serving an existing file does not reseed it."""
    db = tmp_path / "retail.sqlite"
    RetailDomain(db, seed=3).setup()
    RetailDomain(db, seed=3).cancel_order("A1045")
    loaded = domain_from_args(["--db", str(db), "--seed", "3"])
    status = next(row["status"] for row in loaded.snapshot()["orders"] if row["id"] == "A1045")
    assert status == "cancelled"


def test_main_sets_up_and_starts_stdio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The module entry point creates the database and serves on stdio."""
    seen: dict[str, str] = {}

    def fake_run(self: MCPServer[None], transport: str = "stdio", **_kwargs: object) -> None:
        seen["transport"] = transport
        seen["server"] = self.name or ""

    monkeypatch.setattr(MCPServer, "run", fake_run)
    db = tmp_path / "retail.sqlite"
    main(["--db", str(db), "--seed", "4", "--setup"])
    assert seen["transport"] == "stdio"
    assert db.exists()
    assert "A1043" in {row["id"] for row in RetailDomain(db, seed=4).snapshot()["orders"]}
