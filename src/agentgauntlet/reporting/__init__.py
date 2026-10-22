"""HTML reports, Markdown tables, and run comparisons.

Example:
    from agentgauntlet.reporting import leaderboard, regression_lines

    leaderboard([("scripted", 1.0, 0.0)])
"""

from agentgauntlet.reporting.compare import regression_lines
from agentgauntlet.reporting.leaderboard import load_leaderboard
from agentgauntlet.reporting.markdown import leaderboard

__all__ = ["leaderboard", "load_leaderboard", "regression_lines"]
