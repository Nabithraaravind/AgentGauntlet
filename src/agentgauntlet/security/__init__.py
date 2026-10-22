"""Prompt-injection attacks and the guardrails compared against them.

The ASR helpers are loaded on first use. Importing them here at startup would
cycle through the runner, which applies those same guardrails.

Example:
    from agentgauntlet.security import ATTACKS, security_markdown

    len(ATTACKS) >= 8
"""

from typing import TYPE_CHECKING

from agentgauntlet.security.guardrails import policy_allows, present, sanitize, spotlight
from agentgauntlet.security.injections import ATTACKS, Attack, attack_by_id, inject

if TYPE_CHECKING:
    from agentgauntlet.security.suite import SecurityObservation as SecurityObservation
    from agentgauntlet.security.suite import SecurityRow as SecurityRow
    from agentgauntlet.security.suite import attack_succeeded as attack_succeeded
    from agentgauntlet.security.suite import security_markdown as security_markdown
    from agentgauntlet.security.suite import security_rows as security_rows

__all__ = [
    "ATTACKS",
    "Attack",
    "SecurityObservation",
    "SecurityRow",
    "attack_by_id",
    "attack_succeeded",
    "inject",
    "policy_allows",
    "present",
    "sanitize",
    "security_markdown",
    "security_rows",
    "spotlight",
]

_SUITE = {
    "SecurityObservation",
    "SecurityRow",
    "attack_succeeded",
    "security_markdown",
    "security_rows",
}


def __getattr__(name: str) -> object:
    """Load the ASR table helpers the first time a caller asks for them."""
    if name not in _SUITE:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    from agentgauntlet.security import suite as suite_module

    value: object = getattr(suite_module, name)
    globals()[name] = value
    return value
