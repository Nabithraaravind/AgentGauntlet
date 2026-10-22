"""Travel booking world.

Example:
    from pathlib import Path

    from agentgauntlet.domains.travel import TravelDomain

    world = TravelDomain(Path("travel.sqlite"), seed=17)
    world.setup()
"""

from agentgauntlet.domains.travel.domain import TravelDomain

__all__ = ["TravelDomain"]
