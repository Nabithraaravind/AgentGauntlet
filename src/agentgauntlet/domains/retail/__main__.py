"""Run the retail world as an MCP stdio server.

Example:
    python -m agentgauntlet.domains.retail --db retail.sqlite --seed 17 --setup
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agentgauntlet.domains.retail.domain import RetailDomain


def domain_from_args(argv: list[str] | None = None) -> RetailDomain:
    """Build a retail domain from process arguments.

    The database is created when ``--setup`` is set or the file does not exist.
    An existing file is left as it is, so a trial can seed once and then serve.
    """
    parser = argparse.ArgumentParser(description="Serve the retail mock world over MCP stdio.")
    parser.add_argument("--db", required=True, type=Path, help="Path to the SQLite file.")
    parser.add_argument(
        "--seed", type=int, default=0, help="Seed used when the database is created."
    )
    parser.add_argument(
        "--flaky-rate",
        type=float,
        default=0.0,
        help="Chance from 0 to 1 that a tool returns a retryable error.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Replace the database with a freshly seeded one before serving.",
    )
    args = parser.parse_args(argv)
    domain = RetailDomain(args.db, seed=args.seed, flaky_rate=args.flaky_rate)
    if args.setup or not args.db.exists():
        domain.setup()
    return domain


def main(argv: list[str] | None = None) -> None:
    """Seed if needed, then serve tools on stdio until the client disconnects."""
    domain_from_args(argv).mcp_server().run()


if __name__ == "__main__":
    main()
