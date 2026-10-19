"""Mock worlds. Each one is a SQLite database exposed as an MCP server.

Example:
    from pathlib import Path

    from agentgauntlet.domains import RetailDomain

    world = RetailDomain(Path("retail.sqlite"), seed=17)
    world.setup()
    world.snapshot()
"""

from agentgauntlet.domains.retail import RetailDomain

__all__ = ["RetailDomain"]
