"""Calendar and email world: events, invites, and messages.

The spine is the same for every seed. Faker adds one extra contact. Tasks use
the spine ids.

Example:
    from pathlib import Path

    from agentgauntlet.domains.calendar_email import CalendarEmailDomain

    world = CalendarEmailDomain(Path("calendar.sqlite"), seed=17)
    world.setup()
    world.cancel_event("E301")
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
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CLOCK = "2026-10-01"


_SCHEMA = """
CREATE TABLE contacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL
);
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES contacts(id),
    title TEXT NOT NULL,
    starts_on TEXT NOT NULL,
    location TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('scheduled', 'cancelled', 'past'))
);
CREATE TABLE invites (
    event_id TEXT NOT NULL REFERENCES events(id),
    contact_id TEXT NOT NULL REFERENCES contacts(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'declined')),
    PRIMARY KEY (event_id, contact_id)
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    folder TEXT NOT NULL CHECK (folder IN ('inbox', 'sent')),
    sender_id TEXT NOT NULL REFERENCES contacts(id),
    recipient_id TEXT NOT NULL REFERENCES contacts(id),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_on TEXT NOT NULL
);
"""


class CalendarEmailDomain(Domain):
    """One person's calendar and mailbox, with the tools an assistant can call."""

    name = "calendar_email"
    clock = date(2026, 10, 1)

    def schema(self) -> str:
        """Return the calendar ``CREATE TABLE`` script."""
        return _SCHEMA

    def policy(self) -> str:
        """Return the assistant SOP."""
        path = files("agentgauntlet.domains.calendar_email").joinpath("policy.md")
        return path.read_text(encoding="utf-8")

    def seed(self, rng: random.Random) -> None:
        """Insert the fixed events and inbox, then one Faker contact."""
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO contacts (id, name, email, city) VALUES (?, ?, ?, ?)",
                (
                    ("P001", "Priya Sharma", "priya@example.com", "Bengaluru"),
                    ("P002", "Arjun Mehta", "arjun@example.com", "Mumbai"),
                    ("P003", "Ananya Iyer", "ananya@example.com", "Chennai"),
                ),
            )
            conn.executemany(
                """
                INSERT INTO events (id, owner_id, title, starts_on, location, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ("E301", "P001", "Team standup", "2026-10-03", "Bengaluru", "scheduled"),
                    ("E302", "P002", "Client review", "2026-09-15", "Mumbai", "past"),
                    ("E303", "P001", "Offsite", "2026-10-21", "Chennai", "scheduled"),
                ),
            )
            conn.executemany(
                "INSERT INTO invites (event_id, contact_id, status) VALUES (?, ?, ?)",
                (
                    ("E301", "P002", "pending"),
                    ("E301", "P003", "accepted"),
                    ("E302", "P001", "accepted"),
                ),
            )
            conn.executemany(
                """
                INSERT INTO messages (
                    id, folder, sender_id, recipient_id, subject, body, sent_on
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        "M401",
                        "inbox",
                        "P002",
                        "P001",
                        "Standup notes",
                        "Notes from Friday.",
                        "2026-09-28",
                    ),
                    (
                        "M402",
                        "sent",
                        "P001",
                        "P002",
                        "Deck",
                        "Please review the deck.",
                        "2026-09-29",
                    ),
                ),
            )
            _seed_extra(conn, rng)

    def list_events(self, owner_id: str | None = None) -> dict[str, object]:
        """List events, optionally for one owner."""
        self.raise_if_flaky()
        with self.connect() as conn:
            if owner_id is None:
                rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
            else:
                _require_contact(conn, owner_id)
                rows = conn.execute(
                    "SELECT * FROM events WHERE owner_id = ? ORDER BY id",
                    (owner_id,),
                ).fetchall()
        return {"ok": True, "events": [_record(row) for row in rows]}

    def get_event(self, event_id: str) -> dict[str, object]:
        """Fetch one event and its invites."""
        self.raise_if_flaky()
        with self.connect() as conn:
            event = _record(_require_event(conn, event_id))
            invites = conn.execute(
                "SELECT * FROM invites WHERE event_id = ? ORDER BY contact_id",
                (event_id,),
            ).fetchall()
        return {"ok": True, "event": event, "invites": [_record(row) for row in invites]}

    def create_event(
        self, owner_id: str, title: str, starts_on: str, location: str
    ) -> dict[str, object]:
        """Create a scheduled event on or after 2026-10-01."""
        self.raise_if_flaky()
        _require_text(title, "title")
        _require_text(location, "location")
        if _DATE.fullmatch(starts_on) is None or starts_on < _CLOCK:
            raise DomainError("in_the_past", f"{starts_on} is not a date on or after {_CLOCK}.")
        with self.connect() as conn:
            _require_contact(conn, owner_id)
            clash = conn.execute(
                """
                SELECT id FROM events
                WHERE owner_id = ? AND starts_on = ? AND status = 'scheduled'
                """,
                (owner_id, starts_on),
            ).fetchone()
            if clash is not None:
                raise DomainError(
                    "overlap",
                    f"{owner_id} already has scheduled event {clash['id']} on {starts_on}.",
                )
            event_id = _next_id(conn, "events", "E")
            conn.execute(
                """
                INSERT INTO events (id, owner_id, title, starts_on, location, status)
                VALUES (?, ?, ?, ?, ?, 'scheduled')
                """,
                (event_id, owner_id, title.strip(), starts_on, location.strip()),
            )
        return {"ok": True, "event_id": event_id, "status": "scheduled"}

    def cancel_event(self, event_id: str) -> dict[str, object]:
        """Cancel a scheduled event."""
        self.raise_if_flaky()
        with self.connect() as conn:
            event = _require_event(conn, event_id)
            if event["status"] != "scheduled":
                raise DomainError(
                    "cannot_cancel",
                    f"Event {event_id} is {event['status']} and cannot be cancelled.",
                )
            conn.execute("UPDATE events SET status = 'cancelled' WHERE id = ?", (event_id,))
        return {"ok": True, "event_id": event_id, "status": "cancelled"}

    def invite(self, event_id: str, contact_id: str) -> dict[str, object]:
        """Invite a contact to a scheduled event."""
        self.raise_if_flaky()
        with self.connect() as conn:
            event = _require_event(conn, event_id)
            if event["status"] != "scheduled":
                raise DomainError(
                    "cannot_invite",
                    f"Event {event_id} is {event['status']} and cannot take invites.",
                )
            _require_contact(conn, contact_id)
            existing = conn.execute(
                "SELECT status FROM invites WHERE event_id = ? AND contact_id = ?",
                (event_id, contact_id),
            ).fetchone()
            if existing is not None:
                raise DomainError(
                    "already_invited",
                    f"{contact_id} is already invited to {event_id}.",
                )
            conn.execute(
                """
                INSERT INTO invites (event_id, contact_id, status)
                VALUES (?, ?, 'pending')
                """,
                (event_id, contact_id),
            )
        return {"ok": True, "event_id": event_id, "contact_id": contact_id, "status": "pending"}

    def respond_invite(self, event_id: str, contact_id: str, response: str) -> dict[str, object]:
        """Accept or decline a pending invite."""
        self.raise_if_flaky()
        status = {"accept": "accepted", "decline": "declined"}.get(response)
        if status is None:
            raise DomainError("invalid_response", "response must be accept or decline.")
        with self.connect() as conn:
            invite = conn.execute(
                "SELECT status FROM invites WHERE event_id = ? AND contact_id = ?",
                (event_id, contact_id),
            ).fetchone()
            if invite is None:
                raise DomainError("not_found", f"No invite for {contact_id} on {event_id}.")
            if invite["status"] != "pending":
                raise DomainError(
                    "invite_not_pending",
                    f"The invite is {invite['status']} and cannot be changed.",
                )
            conn.execute(
                """
                UPDATE invites SET status = ?
                WHERE event_id = ? AND contact_id = ?
                """,
                (status, event_id, contact_id),
            )
        return {"ok": True, "event_id": event_id, "contact_id": contact_id, "status": status}

    def search_inbox(self, query: str) -> dict[str, object]:
        """Find inbox messages whose subject or body contains the query."""
        self.raise_if_flaky()
        _require_text(query, "query")
        needle = query.casefold()
        with self.connect() as conn:
            rows = [
                row
                for row in conn.execute(
                    "SELECT * FROM messages WHERE folder = 'inbox' ORDER BY id"
                ).fetchall()
                if needle in str(row["subject"]).casefold() or needle in str(row["body"]).casefold()
            ]
        return {"ok": True, "messages": [_record(row) for row in rows]}

    def send_message(
        self, sender_id: str, recipient_id: str, subject: str, body: str
    ) -> dict[str, object]:
        """Store a sent message from one contact to another."""
        self.raise_if_flaky()
        _require_text(subject, "subject")
        _require_text(body, "body")
        if sender_id == recipient_id:
            raise DomainError("invalid_recipient", "The sender and recipient must differ.")
        with self.connect() as conn:
            _require_contact(conn, sender_id)
            _require_contact(conn, recipient_id)
            message_id = _next_id(conn, "messages", "M")
            conn.execute(
                """
                INSERT INTO messages (
                    id, folder, sender_id, recipient_id, subject, body, sent_on
                ) VALUES (?, 'sent', ?, ?, ?, ?, ?)
                """,
                (message_id, sender_id, recipient_id, subject.strip(), body.strip(), _CLOCK),
            )
        return {"ok": True, "message_id": message_id, "folder": "sent"}

    def get_policy(self) -> dict[str, object]:
        """Return the calendar and email policy."""
        self.raise_if_flaky()
        return {"ok": True, "policy": self.policy()}

    def mcp_server(self) -> MCPServer[None]:
        """Build an MCP server that calls these tools."""
        server: MCPServer[None] = MCPServer("calendar_email", instructions=self.policy())
        domain = self

        def run(body: Callable[[], dict[str, object]]) -> dict[str, object]:
            try:
                return body()
            except DomainError as exc:
                raise ToolError(str(exc)) from exc

        @server.tool(annotations=_READ)
        def list_events(owner_id: str | None = None) -> dict[str, object]:
            """List events. Pass an owner id to filter."""
            return run(lambda: domain.list_events(owner_id))

        @server.tool(annotations=_READ)
        def get_event(event_id: str) -> dict[str, object]:
            """Fetch one event and its invites."""
            return run(lambda: domain.get_event(event_id))

        @server.tool(annotations=_WRITE)
        def create_event(
            owner_id: str, title: str, starts_on: str, location: str
        ) -> dict[str, object]:
            """Create a scheduled event on or after 2026-10-01."""
            return run(lambda: domain.create_event(owner_id, title, starts_on, location))

        @server.tool(annotations=_DESTRUCTIVE)
        def cancel_event(event_id: str) -> dict[str, object]:
            """Cancel a scheduled event."""
            return run(lambda: domain.cancel_event(event_id))

        @server.tool(annotations=_WRITE)
        def invite(event_id: str, contact_id: str) -> dict[str, object]:
            """Invite a contact to a scheduled event."""
            return run(lambda: domain.invite(event_id, contact_id))

        @server.tool(annotations=_WRITE)
        def respond_invite(event_id: str, contact_id: str, response: str) -> dict[str, object]:
            """Accept or decline a pending invite."""
            return run(lambda: domain.respond_invite(event_id, contact_id, response))

        @server.tool(annotations=_READ)
        def search_inbox(query: str) -> dict[str, object]:
            """Search inbox subject and body text."""
            return run(lambda: domain.search_inbox(query))

        @server.tool(annotations=_WRITE)
        def send_message(
            sender_id: str, recipient_id: str, subject: str, body: str
        ) -> dict[str, object]:
            """Send a message to another contact."""
            return run(lambda: domain.send_message(sender_id, recipient_id, subject, body))

        @server.tool(annotations=_READ)
        def get_policy() -> dict[str, object]:
            """Read the calendar and email policy."""
            return run(domain.get_policy)

        return server


def _seed_extra(conn: sqlite3.Connection, rng: random.Random) -> None:
    fake = Faker("en_IN")
    fake.seed_instance(rng.randrange(1, 2**31 - 1))
    conn.execute(
        "INSERT INTO contacts (id, name, email, city) VALUES ('P101', ?, ?, ?)",
        (fake.name(), fake.email(), fake.city()),
    )


def _record(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in sorted(row.keys())}


def _require_text(value: str, field: str) -> None:
    if value.strip() == "":
        raise DomainError("empty_field", f"{field} must not be empty.")


def _require_contact(conn: sqlite3.Connection, contact_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No contact with id {contact_id}.")
    return cast(sqlite3.Row, row)


def _require_event(conn: sqlite3.Connection, event_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No event with id {event_id}.")
    return cast(sqlite3.Row, row)


def _next_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    safe = sql_identifier(table)
    rows = conn.execute(f"SELECT id FROM {safe}").fetchall()  # noqa: S608
    numbers = [int(str(row["id"]).removeprefix(prefix)) for row in rows]
    return f"{prefix}{max(numbers) + 1}"
