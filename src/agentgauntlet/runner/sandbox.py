"""Give every trial its own copy of the world database.

The template is built once from the task seed. Each trial copies that file, so
a write in trial 0 cannot change what trial 1 sees.

Example:
    from pathlib import Path

    from agentgauntlet.runner.sandbox import clone_database, materialize_world

    template = materialize_world("retail", Path("template.sqlite"), seed=17)
    clone_database(template.db_path, Path("trial.sqlite"))
"""

from __future__ import annotations

import shutil
from pathlib import Path

from agentgauntlet.domains.base import Domain
from agentgauntlet.domains.retail import RetailDomain


class UnknownDomainError(Exception):
    """The task names a world this build cannot open."""


def domain_for(name: str, db_path: Path, *, seed: int) -> Domain:
    """Open the world named ``name`` on ``db_path`` without seeding it."""
    if name == "retail":
        return RetailDomain(db_path, seed=seed)
    raise UnknownDomainError(f"domain {name!r} has no world yet")


def materialize_world(name: str, db_path: Path, *, seed: int) -> Domain:
    """Create ``db_path`` from the world's schema and seed, and return it."""
    domain = domain_for(name, db_path, seed=seed)
    domain.setup()
    return domain


def clone_database(source: Path, dest: Path) -> None:
    """Copy a SQLite file to ``dest``, replacing anything already there."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
