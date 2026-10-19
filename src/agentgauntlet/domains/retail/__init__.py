"""Retail customer-support world.

Example:
    from pathlib import Path

    from agentgauntlet.domains.retail import RetailDomain

    world = RetailDomain(Path("retail.sqlite"), seed=17)
    world.setup()
"""

from agentgauntlet.domains.retail.domain import RetailDomain

__all__ = ["RetailDomain"]
