"""Travel world: flights, bookings, seats, and loyalty points.

The spine is the same for every seed. Faker adds one extra customer and one
extra flight so the seed still changes the database. Tasks use the spine ids.

Example:
    from pathlib import Path

    from agentgauntlet.domains.travel import TravelDomain

    world = TravelDomain(Path("travel.sqlite"), seed=17)
    world.setup()
    world.book_flight("C003", "F104")
"""

from __future__ import annotations

import random
import re
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
_SEAT = re.compile(r"^[0-9]{1,2}[A-F]$")
_CLOCK = date(2026, 10, 1)

_SCHEMA = """
CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL,
    loyalty_points INTEGER NOT NULL CHECK (loyalty_points >= 0)
);
CREATE TABLE flights (
    id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departs_on TEXT NOT NULL,
    fare_inr INTEGER NOT NULL,
    seats_left INTEGER NOT NULL CHECK (seats_left >= 0),
    status TEXT NOT NULL CHECK (status IN ('scheduled', 'departed'))
);
CREATE TABLE bookings (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    flight_id TEXT NOT NULL REFERENCES flights(id),
    status TEXT NOT NULL CHECK (status IN ('booked', 'cancelled', 'completed')),
    fare_inr INTEGER NOT NULL,
    seat_code TEXT
);
CREATE TABLE loyalty_events (
    id INTEGER PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    points INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('earn', 'redeem')),
    booking_id TEXT
);
"""


class TravelDomain(Domain):
    """A small airline database and the tools a booking agent can call."""

    name = "travel"
    clock = _CLOCK

    def schema(self) -> str:
        """Return the travel ``CREATE TABLE`` script."""
        return _SCHEMA

    def policy(self) -> str:
        """Return the booking SOP."""
        path = files("agentgauntlet.domains.travel").joinpath("policy.md")
        return path.read_text(encoding="utf-8")

    def seed(self, rng: random.Random) -> None:
        """Insert the fixed flights and bookings, then one Faker customer."""
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO customers (id, name, email, city, loyalty_points)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ("C001", "Priya Sharma", "priya@example.com", "Bengaluru", 1500),
                    ("C002", "Arjun Mehta", "arjun@example.com", "Mumbai", 200),
                    ("C003", "Ananya Iyer", "ananya@example.com", "Chennai", 900),
                ),
            )
            conn.executemany(
                """
                INSERT INTO flights (
                    id, origin, destination, departs_on, fare_inr, seats_left, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ("F101", "BLR", "BOM", "2026-10-15", 4500, 4, "scheduled"),
                    ("F102", "BOM", "MAA", "2026-10-20", 3800, 0, "scheduled"),
                    ("F103", "MAA", "BLR", "2026-09-20", 3200, 6, "departed"),
                    ("F104", "BLR", "MAA", "2026-10-25", 5100, 3, "scheduled"),
                ),
            )
            conn.executemany(
                """
                INSERT INTO bookings (
                    id, customer_id, flight_id, status, fare_inr, seat_code
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ("B2001", "C001", "F101", "booked", 4500, "12A"),
                    ("B2002", "C002", "F103", "completed", 3200, "4C"),
                ),
            )
            _seed_extra(conn, rng)

    def search_flights(self, origin: str, destination: str) -> dict[str, object]:
        """Find scheduled and departed flights between two city codes."""
        self.raise_if_flaky()
        _require_text(origin, "origin")
        _require_text(destination, "destination")
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM flights
                WHERE origin = ? AND destination = ?
                ORDER BY departs_on
                """,
                (origin.strip(), destination.strip()),
            ).fetchall()
        return {"ok": True, "flights": [_record(row) for row in rows]}

    def get_flight(self, flight_id: str) -> dict[str, object]:
        """Fetch one flight."""
        self.raise_if_flaky()
        with self.connect() as conn:
            return {"ok": True, "flight": _record(_require_flight(conn, flight_id))}

    def get_booking(self, booking_id: str) -> dict[str, object]:
        """Fetch one booking."""
        self.raise_if_flaky()
        with self.connect() as conn:
            return {"ok": True, "booking": _record(_require_booking(conn, booking_id))}

    def list_bookings(self, customer_id: str) -> dict[str, object]:
        """List every booking for a customer."""
        self.raise_if_flaky()
        with self.connect() as conn:
            _require_customer(conn, customer_id)
            rows = conn.execute(
                "SELECT * FROM bookings WHERE customer_id = ? ORDER BY id",
                (customer_id,),
            ).fetchall()
        return {"ok": True, "bookings": [_record(row) for row in rows]}

    def book_flight(self, customer_id: str, flight_id: str) -> dict[str, object]:
        """Hold one seat and earn fare // 10 loyalty points."""
        self.raise_if_flaky()
        with self.connect() as conn:
            _require_customer(conn, customer_id)
            flight = _require_flight(conn, flight_id)
            if flight["status"] != "scheduled":
                raise DomainError("departed", f"Flight {flight_id} has already departed.")
            if int(flight["seats_left"]) < 1:
                raise DomainError("full", f"Flight {flight_id} has no seats left.")
            held = conn.execute(
                """
                SELECT id FROM bookings
                WHERE customer_id = ? AND flight_id = ? AND status = 'booked'
                """,
                (customer_id, flight_id),
            ).fetchone()
            if held is not None:
                raise DomainError(
                    "already_booked",
                    f"{customer_id} already has booking {held['id']} on {flight_id}.",
                )
            booking_id = _next_id(conn, "bookings", "B")
            fare = int(flight["fare_inr"])
            points = fare // 10
            conn.execute(
                """
                INSERT INTO bookings (id, customer_id, flight_id, status, fare_inr, seat_code)
                VALUES (?, ?, ?, 'booked', ?, NULL)
                """,
                (booking_id, customer_id, flight_id, fare),
            )
            conn.execute(
                "UPDATE flights SET seats_left = seats_left - 1 WHERE id = ?",
                (flight_id,),
            )
            conn.execute(
                "UPDATE customers SET loyalty_points = loyalty_points + ? WHERE id = ?",
                (points, customer_id),
            )
            conn.execute(
                """
                INSERT INTO loyalty_events (customer_id, points, kind, booking_id)
                VALUES (?, ?, 'earn', ?)
                """,
                (customer_id, points, booking_id),
            )
        return {
            "ok": True,
            "booking_id": booking_id,
            "fare_inr": fare,
            "points_earned": points,
        }

    def cancel_booking(self, booking_id: str) -> dict[str, object]:
        """Cancel a booked seat on a flight that has not departed."""
        self.raise_if_flaky()
        with self.connect() as conn:
            booking = _require_booking(conn, booking_id)
            if booking["status"] != "booked":
                raise DomainError(
                    "cannot_cancel",
                    f"Booking {booking_id} is {booking['status']} and cannot be cancelled.",
                )
            flight = _require_flight(conn, str(booking["flight_id"]))
            if flight["status"] != "scheduled":
                raise DomainError("departed", f"Flight {flight['id']} has already departed.")
            conn.execute(
                "UPDATE bookings SET status = 'cancelled', seat_code = NULL WHERE id = ?",
                (booking_id,),
            )
            conn.execute(
                "UPDATE flights SET seats_left = seats_left + 1 WHERE id = ?",
                (flight["id"],),
            )
        return {"ok": True, "booking_id": booking_id, "status": "cancelled"}

    def assign_seat(self, booking_id: str, seat_code: str) -> dict[str, object]:
        """Put an active booking in a free seat."""
        self.raise_if_flaky()
        if _SEAT.fullmatch(seat_code.strip()) is None:
            raise DomainError("invalid_seat", f"Seat {seat_code!r} is not a code like 12A.")
        seat = seat_code.strip()
        with self.connect() as conn:
            booking = _require_booking(conn, booking_id)
            if booking["status"] != "booked":
                raise DomainError(
                    "not_active",
                    f"Booking {booking_id} is {booking['status']} and has no seat to change.",
                )
            taken = conn.execute(
                """
                SELECT id FROM bookings
                WHERE flight_id = ? AND status = 'booked' AND seat_code = ? AND id != ?
                """,
                (booking["flight_id"], seat, booking_id),
            ).fetchone()
            if taken is not None:
                raise DomainError("seat_taken", f"Seat {seat} is already held by {taken['id']}.")
            conn.execute(
                "UPDATE bookings SET seat_code = ? WHERE id = ?",
                (seat, booking_id),
            )
        return {"ok": True, "booking_id": booking_id, "seat_code": seat}

    def redeem_points(self, customer_id: str, points: int) -> dict[str, object]:
        """Spend a positive number of loyalty points."""
        self.raise_if_flaky()
        if type(points) is not int or points <= 0:
            raise DomainError("invalid_points", "points must be a positive integer.")
        with self.connect() as conn:
            customer = _require_customer(conn, customer_id)
            balance = int(customer["loyalty_points"])
            if points > balance:
                raise DomainError(
                    "insufficient_points",
                    f"{customer_id} has {balance} points, which is less than {points}.",
                )
            conn.execute(
                "UPDATE customers SET loyalty_points = loyalty_points - ? WHERE id = ?",
                (points, customer_id),
            )
            conn.execute(
                """
                INSERT INTO loyalty_events (customer_id, points, kind, booking_id)
                VALUES (?, ?, 'redeem', NULL)
                """,
                (customer_id, points),
            )
        return {"ok": True, "customer_id": customer_id, "loyalty_points": balance - points}

    def get_policy(self) -> dict[str, object]:
        """Return the booking policy."""
        self.raise_if_flaky()
        return {"ok": True, "policy": self.policy()}

    def mcp_server(self) -> MCPServer[None]:
        """Build an MCP server that calls these tools."""
        server: MCPServer[None] = MCPServer("travel", instructions=self.policy())
        domain = self

        def run(body: Callable[[], dict[str, object]]) -> dict[str, object]:
            try:
                return body()
            except DomainError as exc:
                raise ToolError(str(exc)) from exc

        @server.tool(annotations=_READ)
        def search_flights(origin: str, destination: str) -> dict[str, object]:
            """Search flights by origin and destination city codes."""
            return run(lambda: domain.search_flights(origin, destination))

        @server.tool(annotations=_READ)
        def get_flight(flight_id: str) -> dict[str, object]:
            """Fetch one flight."""
            return run(lambda: domain.get_flight(flight_id))

        @server.tool(annotations=_READ)
        def get_booking(booking_id: str) -> dict[str, object]:
            """Fetch one booking."""
            return run(lambda: domain.get_booking(booking_id))

        @server.tool(annotations=_READ)
        def list_bookings(customer_id: str) -> dict[str, object]:
            """List a customer's bookings."""
            return run(lambda: domain.list_bookings(customer_id))

        @server.tool(annotations=_WRITE)
        def book_flight(customer_id: str, flight_id: str) -> dict[str, object]:
            """Book one seat on a scheduled flight."""
            return run(lambda: domain.book_flight(customer_id, flight_id))

        @server.tool(annotations=_DESTRUCTIVE)
        def cancel_booking(booking_id: str) -> dict[str, object]:
            """Cancel a booking that has not departed."""
            return run(lambda: domain.cancel_booking(booking_id))

        @server.tool(annotations=_WRITE)
        def assign_seat(booking_id: str, seat_code: str) -> dict[str, object]:
            """Assign a free seat code on an active booking."""
            return run(lambda: domain.assign_seat(booking_id, seat_code))

        @server.tool(annotations=_WRITE)
        def redeem_points(customer_id: str, points: int) -> dict[str, object]:
            """Redeem a positive number of loyalty points."""
            return run(lambda: domain.redeem_points(customer_id, points))

        @server.tool(annotations=_READ)
        def get_policy() -> dict[str, object]:
            """Read the travel booking policy."""
            return run(domain.get_policy)

        return server


def _seed_extra(conn: sqlite3.Connection, rng: random.Random) -> None:
    fake = Faker("en_IN")
    fake.seed_instance(rng.randrange(1, 2**31 - 1))
    conn.execute(
        """
        INSERT INTO customers (id, name, email, city, loyalty_points)
        VALUES ('C101', ?, ?, ?, 100)
        """,
        (fake.name(), fake.email(), fake.city()),
    )
    conn.execute(
        """
        INSERT INTO flights (
            id, origin, destination, departs_on, fare_inr, seats_left, status
        ) VALUES ('F901', 'BLR', 'MAA', '2026-11-02', ?, 8, 'scheduled')
        """,
        (3000 + rng.randrange(0, 5) * 100,),
    )


def _record(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in sorted(row.keys())}


def _require_text(value: str, field: str) -> None:
    if value.strip() == "":
        raise DomainError("empty_field", f"{field} must not be empty.")


def _require_customer(conn: sqlite3.Connection, customer_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No customer with id {customer_id}.")
    return cast(sqlite3.Row, row)


def _require_flight(conn: sqlite3.Connection, flight_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No flight with id {flight_id}.")
    return cast(sqlite3.Row, row)


def _require_booking(conn: sqlite3.Connection, booking_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No booking with id {booking_id}.")
    return cast(sqlite3.Row, row)


def _next_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    safe = sql_identifier(table)
    rows = conn.execute(f"SELECT id FROM {safe}").fetchall()  # noqa: S608
    numbers = [int(str(row["id"]).removeprefix(prefix)) for row in rows]
    return f"{prefix}{max(numbers) + 1}"
