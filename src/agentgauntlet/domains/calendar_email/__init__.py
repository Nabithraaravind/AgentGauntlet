"""Calendar and email world.

Example:
    from pathlib import Path

    from agentgauntlet.domains.calendar_email import CalendarEmailDomain

    world = CalendarEmailDomain(Path("calendar.sqlite"), seed=17)
    world.setup()
"""

from agentgauntlet.domains.calendar_email.domain import CalendarEmailDomain

__all__ = ["CalendarEmailDomain"]
