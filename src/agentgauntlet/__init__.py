"""AgentGauntlet: pytest for AI agents.

State-based grading of tool-using agents against mock MCP servers.
This module is the public package entry point. Later milestones add the
runner, domains, and grading APIs beside it.

The version string comes from the installed distribution, which hatchling
reads from ``pyproject.toml``. There is one place to bump it.

Example:
    import agentgauntlet

    print(agentgauntlet.__version__)
"""

from __future__ import annotations

from importlib.metadata import version

__version__ = version("agentgauntlet")

__all__ = ["__version__"]
