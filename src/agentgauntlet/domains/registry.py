"""Map a task's domain name to the world that opens it.

The tasks package imports this module. It must not import the runner, or the
agent package and the task package load each other in a circle.

Example:
    from pathlib import Path

    from agentgauntlet.domains.registry import domain_for

    world = domain_for("travel", Path("travel.sqlite"), seed=17)
    world.setup()
"""

from __future__ import annotations

from pathlib import Path

from agentgauntlet.domains.banking import BankingDomain
from agentgauntlet.domains.base import Domain
from agentgauntlet.domains.calendar_email import CalendarEmailDomain
from agentgauntlet.domains.retail import RetailDomain
from agentgauntlet.domains.travel import TravelDomain


class UnknownDomainError(Exception):
    """The task names a world this build cannot open."""


def domain_for(name: str, db_path: Path, *, seed: int) -> Domain:
    """Open the world named ``name`` on ``db_path`` without seeding it."""
    worlds: dict[str, type[Domain]] = {
        "retail": RetailDomain,
        "travel": TravelDomain,
        "calendar_email": CalendarEmailDomain,
        "banking": BankingDomain,
    }
    kind = worlds.get(name)
    if kind is None:
        raise UnknownDomainError(f"domain {name!r} has no world yet")
    return kind(db_path, seed=seed)
