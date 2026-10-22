"""Call every travel, calendar, and banking tool through an MCP client."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pytest
from mcp import Client
from mcp.types import TextContent

from agentgauntlet.domains.banking import BankingDomain
from agentgauntlet.domains.base import Domain, DomainError
from agentgauntlet.domains.calendar_email import CalendarEmailDomain
from agentgauntlet.domains.travel import TravelDomain
from agentgauntlet.tasks.replay import BANKING_TABLES, CALENDAR_TABLES, TRAVEL_TABLES

World = TypeVar("World", bound=Domain)


def _world(kind: type[World], tmp_path: Path, *, flaky_rate: float = 0.0) -> World:
    domain = kind(tmp_path / "world.sqlite", seed=17, flaky_rate=flaky_rate)
    domain.setup()
    return domain


async def _call(domain: Domain, tool: str, arguments: dict[str, object]) -> object:
    async with Client(domain.mcp_server(), raise_exceptions=True) as client:
        return await client.call_tool(tool, arguments)


def _ok(result: object) -> dict[str, object]:
    assert getattr(result, "is_error", None) is False
    content = getattr(result, "structured_content", None)
    assert isinstance(content, dict)
    return content


def _row(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _err(result: object) -> str:
    assert getattr(result, "is_error", None) is True
    block = result.content[0]  # type: ignore[attr-defined]
    assert isinstance(block, TextContent)
    return block.text


async def test_travel_tools_follow_the_booking_rules(tmp_path: Path) -> None:
    """Every travel tool is listed, and each business rule has its error code."""
    world = _world(TravelDomain, tmp_path)
    assert set(world.snapshot()) == TRAVEL_TABLES
    async with Client(world.mcp_server(), raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == {
        "assign_seat",
        "book_flight",
        "cancel_booking",
        "get_booking",
        "get_flight",
        "get_policy",
        "list_bookings",
        "redeem_points",
        "search_flights",
    }
    assert "F101" in str(
        _ok(await _call(world, "search_flights", {"origin": "BLR", "destination": "BOM"}))
    )
    flight = _row(_ok(await _call(world, "get_flight", {"flight_id": "F102"}))["flight"])
    assert flight["seats_left"] == 0
    booking = _row(_ok(await _call(world, "get_booking", {"booking_id": "B2001"}))["booking"])
    assert booking["status"] == "booked"
    listed = _ok(await _call(world, "list_bookings", {"customer_id": "C001"}))
    assert listed["bookings"][0]["id"] == "B2001"  # type: ignore[index]
    assert "departed" in str(_ok(await _call(world, "get_policy", {}))["policy"])

    booked = _ok(await _call(world, "book_flight", {"customer_id": "C003", "flight_id": "F104"}))
    assert booked["booking_id"] == "B2003"
    assert booked["points_earned"] == 510
    seated = _ok(await _call(world, "assign_seat", {"booking_id": "B2003", "seat_code": "14A"}))
    assert seated["seat_code"] == "14A"
    redeemed = _ok(await _call(world, "redeem_points", {"customer_id": "C002", "points": 100}))
    assert redeemed["loyalty_points"] == 100
    cancelled = _ok(await _call(world, "cancel_booking", {"booking_id": "B2001"}))
    assert cancelled["status"] == "cancelled"

    assert "empty_field" in _err(
        await _call(world, "search_flights", {"origin": " ", "destination": "BOM"})
    )
    assert "not_found" in _err(await _call(world, "get_flight", {"flight_id": "F999"}))
    assert "not_found" in _err(await _call(world, "get_booking", {"booking_id": "B9"}))
    assert "not_found" in _err(await _call(world, "list_bookings", {"customer_id": "C999"}))
    assert "departed" in _err(
        await _call(world, "book_flight", {"customer_id": "C003", "flight_id": "F103"})
    )
    assert "full" in _err(
        await _call(world, "book_flight", {"customer_id": "C002", "flight_id": "F102"})
    )
    assert "already_booked" in _err(
        await _call(world, "book_flight", {"customer_id": "C003", "flight_id": "F104"})
    )
    assert "cannot_cancel" in _err(await _call(world, "cancel_booking", {"booking_id": "B2002"}))
    assert "invalid_seat" in _err(
        await _call(world, "assign_seat", {"booking_id": "B2003", "seat_code": "window"})
    )
    assert "not_active" in _err(
        await _call(world, "assign_seat", {"booking_id": "B2002", "seat_code": "1A"})
    )
    assert "insufficient_points" in _err(
        await _call(world, "redeem_points", {"customer_id": "C002", "points": 500})
    )
    with pytest.raises(DomainError, match="invalid_points"):
        world.redeem_points("C002", True)
    with pytest.raises(DomainError, match="invalid_points"):
        world.redeem_points("C002", 0)

    fresh = _world(TravelDomain, tmp_path / "seat")
    _ok(await _call(fresh, "book_flight", {"customer_id": "C002", "flight_id": "F101"}))
    assert "seat_taken" in _err(
        await _call(fresh, "assign_seat", {"booking_id": "B2003", "seat_code": "12A"})
    )
    gone = _world(TravelDomain, tmp_path / "departed")
    _ok(await _call(gone, "book_flight", {"customer_id": "C001", "flight_id": "F104"}))
    with gone.connect() as conn:
        conn.execute("UPDATE flights SET status = 'departed' WHERE id = 'F104'")
    with pytest.raises(DomainError, match="departed"):
        gone.cancel_booking("B2003")


async def test_travel_flaky_mode_is_retryable(tmp_path: Path) -> None:
    """A flaky travel tool fails before it reads the database."""
    world = _world(TravelDomain, tmp_path / "flaky", flaky_rate=1.0)
    assert "retryable" in _err(await _call(world, "get_policy", {})).casefold()


async def test_calendar_tools_follow_the_schedule_rules(tmp_path: Path) -> None:
    """Every calendar tool is listed, and past events stay past."""
    world = _world(CalendarEmailDomain, tmp_path)
    assert set(world.snapshot()) == CALENDAR_TABLES
    async with Client(world.mcp_server(), raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert "send_message" in names
    assert "create_event" in names
    events = _ok(await _call(world, "list_events", {}))
    assert len(events["events"]) >= 3  # type: ignore[arg-type]
    owned = _ok(await _call(world, "list_events", {"owner_id": "P002"}))
    assert owned["events"][0]["id"] == "E302"  # type: ignore[index]
    event = _ok(await _call(world, "get_event", {"event_id": "E301"}))
    assert len(event["invites"]) == 2  # type: ignore[arg-type]
    created = _ok(
        await _call(
            world,
            "create_event",
            {
                "owner_id": "P002",
                "title": "Planning",
                "starts_on": "2026-10-30",
                "location": "Hyderabad",
            },
        )
    )
    assert created["event_id"] == "E304"
    invited = _ok(await _call(world, "invite", {"event_id": "E303", "contact_id": "P002"}))
    assert invited["status"] == "pending"
    accepted = _ok(
        await _call(
            world,
            "respond_invite",
            {"event_id": "E301", "contact_id": "P002", "response": "accept"},
        )
    )
    assert accepted["status"] == "accepted"
    found = _ok(await _call(world, "search_inbox", {"query": "notes"}))
    assert found["messages"][0]["id"] == "M401"  # type: ignore[index]
    sent = _ok(
        await _call(
            world,
            "send_message",
            {
                "sender_id": "P001",
                "recipient_id": "P003",
                "subject": "Hello",
                "body": "See you there.",
            },
        )
    )
    assert sent["message_id"] == "M403"
    cancelled = _ok(await _call(world, "cancel_event", {"event_id": "E303"}))
    assert cancelled["status"] == "cancelled"
    assert "scheduled" in str(_ok(await _call(world, "get_policy", {}))["policy"])

    assert "not_found" in _err(await _call(world, "get_event", {"event_id": "E999"}))
    assert "not_found" in _err(await _call(world, "list_events", {"owner_id": "P999"}))
    assert "empty_field" in _err(
        await _call(
            world,
            "create_event",
            {"owner_id": "P002", "title": " ", "starts_on": "2026-11-01", "location": "Pune"},
        )
    )
    assert "in_the_past" in _err(
        await _call(
            world,
            "create_event",
            {"owner_id": "P002", "title": "Old", "starts_on": "2026-09-01", "location": "Pune"},
        )
    )
    assert "overlap" in _err(
        await _call(
            world,
            "create_event",
            {"owner_id": "P001", "title": "Clash", "starts_on": "2026-10-03", "location": "Pune"},
        )
    )
    assert "cannot_cancel" in _err(await _call(world, "cancel_event", {"event_id": "E302"}))
    assert "cannot_invite" in _err(
        await _call(world, "invite", {"event_id": "E302", "contact_id": "P003"})
    )
    assert "already_invited" in _err(
        await _call(world, "invite", {"event_id": "E301", "contact_id": "P003"})
    )
    assert "invalid_response" in _err(
        await _call(
            world,
            "respond_invite",
            {"event_id": "E301", "contact_id": "P003", "response": "maybe"},
        )
    )
    assert "not_found" in _err(
        await _call(
            world,
            "respond_invite",
            {"event_id": "E301", "contact_id": "P101", "response": "decline"},
        )
    )
    assert "invite_not_pending" in _err(
        await _call(
            world,
            "respond_invite",
            {"event_id": "E301", "contact_id": "P003", "response": "decline"},
        )
    )
    assert "empty_field" in _err(await _call(world, "search_inbox", {"query": " "}))
    assert "invalid_recipient" in _err(
        await _call(
            world,
            "send_message",
            {"sender_id": "P001", "recipient_id": "P001", "subject": "Me", "body": "Hi"},
        )
    )
    assert "not_found" in _err(
        await _call(
            world,
            "send_message",
            {"sender_id": "P001", "recipient_id": "P999", "subject": "Hi", "body": "Hi"},
        )
    )
    _ok(await _call(world, "invite", {"event_id": "E304", "contact_id": "P001"}))
    declined = _ok(
        await _call(
            world,
            "respond_invite",
            {"event_id": "E304", "contact_id": "P001", "response": "decline"},
        )
    )
    assert declined["status"] == "declined"
    friday = _ok(await _call(world, "search_inbox", {"query": "friday"}))
    assert friday["messages"][0]["id"] == "M401"  # type: ignore[index]
    assert "in_the_past" in _err(
        await _call(
            world,
            "create_event",
            {"owner_id": "P002", "title": "Nope", "starts_on": "tomorrow", "location": "Pune"},
        )
    )


async def test_calendar_flaky_mode_is_retryable(tmp_path: Path) -> None:
    """A flaky calendar tool fails before it reads the database."""
    world = _world(CalendarEmailDomain, tmp_path / "flaky", flaky_rate=1.0)
    assert "retryable" in _err(await _call(world, "get_policy", {})).casefold()


async def test_banking_tools_follow_the_transfer_rules(tmp_path: Path) -> None:
    """Small transfers post, large ones wait, and a frozen account cannot send."""
    world = _world(BankingDomain, tmp_path)
    assert set(world.snapshot()) == BANKING_TABLES
    async with Client(world.mcp_server(), raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert "confirm_transfer" in names
    assert "cancel_transfer" in names
    account = _ok(await _call(world, "get_account", {"account_id": "AC01"}))
    assert account["account"]["balance_inr"] == 80000  # type: ignore[index]
    accounts = _ok(await _call(world, "list_accounts", {"customer_id": "C001"}))
    assert accounts["accounts"][0]["id"] == "AC01"  # type: ignore[index]
    payees = _ok(await _call(world, "list_payees", {}))
    assert len(payees["payees"]) == 3  # type: ignore[arg-type]
    added = _ok(await _call(world, "add_payee", {"name": "Cafe", "account_number": "555666777"}))
    assert added["payee_id"] == "PY04"
    verified = _ok(await _call(world, "verify_payee", {"payee_id": "PY04"}))
    assert verified["verified"] == 1
    posted = _ok(
        await _call(
            world, "transfer", {"account_id": "AC02", "payee_id": "PY03", "amount_inr": 1000}
        )
    )
    assert posted["transfer_id"] == "T502"
    assert posted["status"] == "posted"
    pending = _ok(
        await _call(
            world, "transfer", {"account_id": "AC01", "payee_id": "PY01", "amount_inr": 25000}
        )
    )
    assert pending["status"] == "pending"
    confirmed = _ok(await _call(world, "confirm_transfer", {"transfer_id": pending["transfer_id"]}))
    assert confirmed["status"] == "posted"
    waiting = _ok(
        await _call(
            world, "transfer", {"account_id": "AC01", "payee_id": "PY01", "amount_inr": 21000}
        )
    )
    rejected = _ok(await _call(world, "cancel_transfer", {"transfer_id": waiting["transfer_id"]}))
    assert rejected["status"] == "rejected"
    assert "20000" in str(_ok(await _call(world, "get_policy", {}))["policy"])

    assert "not_found" in _err(await _call(world, "get_account", {"account_id": "AC99"}))
    assert "not_found" in _err(await _call(world, "list_accounts", {"customer_id": "C999"}))
    assert "invalid_account" in _err(
        await _call(world, "add_payee", {"name": "X", "account_number": "12"})
    )
    assert "invalid_account" in _err(
        await _call(world, "add_payee", {"name": "X", "account_number": "abc"})
    )
    assert "empty_field" in _err(
        await _call(world, "add_payee", {"name": " ", "account_number": "123456"})
    )
    assert "already_verified" in _err(await _call(world, "verify_payee", {"payee_id": "PY01"}))
    assert "not_found" in _err(await _call(world, "verify_payee", {"payee_id": "PY99"}))
    assert "frozen" in _err(
        await _call(
            world, "transfer", {"account_id": "AC03", "payee_id": "PY01", "amount_inr": 100}
        )
    )
    assert "unverified_payee" in _err(
        await _call(
            world, "transfer", {"account_id": "AC02", "payee_id": "PY02", "amount_inr": 100}
        )
    )
    assert "insufficient_funds" in _err(
        await _call(
            world, "transfer", {"account_id": "AC02", "payee_id": "PY03", "amount_inr": 20000}
        )
    )
    assert "not_pending" in _err(await _call(world, "confirm_transfer", {"transfer_id": "T501"}))
    assert "not_found" in _err(await _call(world, "cancel_transfer", {"transfer_id": "T999"}))
    with pytest.raises(DomainError, match="invalid_amount"):
        world.transfer("AC01", "PY01", True)
    with pytest.raises(DomainError, match="invalid_amount"):
        world.transfer("AC01", "PY01", 0)


async def test_banking_flaky_mode_is_retryable(tmp_path: Path) -> None:
    """A flaky banking tool fails before it reads the database."""
    world = _world(BankingDomain, tmp_path / "flaky", flaky_rate=1.0)
    assert "retryable" in _err(await _call(world, "get_policy", {})).casefold()
