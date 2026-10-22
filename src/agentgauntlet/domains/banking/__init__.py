"""Banking world.

Example:
    from pathlib import Path

    from agentgauntlet.domains.banking import BankingDomain

    world = BankingDomain(Path("banking.sqlite"), seed=17)
    world.setup()
"""

from agentgauntlet.domains.banking.domain import BankingDomain

__all__ = ["BankingDomain"]
