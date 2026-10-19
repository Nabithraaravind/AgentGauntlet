"""Base class for a mock world.

A domain owns one SQLite file. ``setup()`` builds the schema and seeds it.
``mcp_server()`` exposes the world's tools. ``snapshot()`` is the graded view
of the database: every table, rows sorted, keys sorted.

Example:
    from pathlib import Path

    from agentgauntlet.domains import RetailDomain

    world = RetailDomain(Path("retail.sqlite"), seed=17)
    world.setup()
    orders = world.snapshot()["orders"]
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

from mcp.server import MCPServer

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DomainError(Exception):
    """A failure a tool should show to the agent.

    ``code`` is a stable token such as ``cannot_cancel``. The string form is
    ``code: message``, which is what the MCP client returns to the model.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        """Store a stable error code and the sentence the agent will read."""
        self.code = code
        self.retryable = retryable
        text = f"{code}: {message}"
        if retryable:
            text = f"{text} This error is retryable."
        super().__init__(text)


def sql_identifier(name: str) -> str:
    """Return ``name`` when it is a plain SQL identifier.

    Snapshot queries interpolate table names. Values from the database still
    have to look like identifiers before they are allowed into SQL text.
    """
    if _IDENTIFIER.fullmatch(name) is None:
        raise ValueError(f"Refusing SQL identifier {name!r}")
    return name


class Domain(ABC):
    """One mock backend: schema, seed data, tools, and a snapshot."""

    name: ClassVar[str]

    def __init__(self, db_path: Path, *, seed: int = 0, flaky_rate: float = 0.0) -> None:
        """Bind the domain to a database file.

        Args:
            db_path: SQLite file. ``setup()`` replaces it.
            seed: Seed for ``random.Random`` and for the flaky-error draw.
            flaky_rate: Chance, from 0 to 1, that a tool fails before touching
                the database. Zero disables the behavior.
        """
        if not 0.0 <= flaky_rate <= 1.0:
            raise ValueError("flaky_rate must be between 0 and 1")
        self.db_path = db_path
        self.seed_value = seed
        self.flaky_rate = flaky_rate
        # Separate stream from seed data, so turning flaky mode on does not
        # change which rows were inserted.
        self._flaky_rng = random.Random(seed + 91_337)

    @abstractmethod
    def schema(self) -> str:
        """Return the ``CREATE TABLE`` script for this world."""

    @abstractmethod
    def seed(self, rng: random.Random) -> None:
        """Insert the world's starting rows.

        ``rng`` is the only source of randomness. The same seed must produce
        the same rows.
        """

    @abstractmethod
    def policy(self) -> str:
        """Return the SOP markdown the agent is supposed to follow."""

    @abstractmethod
    def mcp_server(self) -> MCPServer[None]:
        """Return an MCP server whose tools read and write this database."""

    def setup(self) -> None:
        """Create a fresh database, apply the schema, and seed it."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        with self.connect() as conn:
            conn.executescript(self.schema())
        self.seed(random.Random(self.seed_value))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection with foreign keys enabled.

        Each tool call opens its own connection and closes it before returning,
        so trials do not share a connection across threads.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        """Return a canonical copy of every user table.

        Tables are sorted by name. Rows are sorted by their JSON form. Keys
        inside a row are sorted. Two equal worlds therefore compare equal.
        """
        with self.connect() as conn:
            table_names = [
                str(row["name"])
                for row in conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                )
            ]
            world: dict[str, list[dict[str, object]]] = {}
            for table in table_names:
                safe = sql_identifier(table)
                records = [
                    {key: record[key] for key in sorted(record.keys())}
                    for record in conn.execute(f"SELECT * FROM {safe}").fetchall()  # noqa: S608
                ]
                records.sort(key=lambda record: json.dumps(record, sort_keys=True, default=str))
                world[table] = records
            return world

    def raise_if_flaky(self) -> None:
        """Maybe raise a retryable error before a tool touches the database.

        The draw is seeded, so a replay with the same seed fails on the same
        calls. The error is returned to the caller instead of sleeping.
        """
        if self.flaky_rate <= 0 or self._flaky_rng.random() >= self.flaky_rate:
            return
        if self._flaky_rng.random() < 0.5:
            raise DomainError(
                "timeout",
                "The tool timed out before the database responded.",
                retryable=True,
            )
        raise DomainError(
            "internal",
            "The tool failed with an internal error (500).",
            retryable=True,
        )
