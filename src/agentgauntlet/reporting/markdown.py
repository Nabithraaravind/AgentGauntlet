"""Markdown tables for a README or a pull-request comment.

Example:
    from agentgauntlet.reporting.markdown import leaderboard

    leaderboard([("scripted", 1.0, 0.0)])
"""

from __future__ import annotations

from collections.abc import Sequence


def leaderboard(rows: Sequence[tuple[str, float, float | None]]) -> str:
    """Render model, pass@1, and cost per success."""
    lines = ["| Model | pass@1 | Cost per success |", "| --- | --- | --- |"]
    for name, pass_at_1, cost in rows:
        cost_text = "n/a" if cost is None else f"{cost:.4f}"
        lines.append(f"| {name} | {pass_at_1:.3f} | {cost_text} |")
    return "\n".join(lines) + "\n"
