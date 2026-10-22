"""Mock worlds. Each one is a SQLite database exposed as an MCP server.

Example:
    from pathlib import Path

    from agentgauntlet.domains import RetailDomain

    world = RetailDomain(Path("retail.sqlite"), seed=17)
    world.setup()
    world.snapshot()
"""

from agentgauntlet.domains.banking import BankingDomain
from agentgauntlet.domains.calendar_email import CalendarEmailDomain
from agentgauntlet.domains.retail import RetailDomain
from agentgauntlet.domains.travel import TravelDomain

__all__ = ["BankingDomain", "CalendarEmailDomain", "RetailDomain", "TravelDomain"]
