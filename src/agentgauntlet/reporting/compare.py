"""Diff two runs by pass@1.

A regression is a task whose pass rate fell. Tasks that exist on only one
side are listed too, so a dropped task is visible.

Example:
    from agentgauntlet.reporting.compare import regression_lines

    regression_lines({"retail-001": 1.0}, {"retail-001": 0.0})
"""

from __future__ import annotations

from collections.abc import Mapping


def regression_lines(before: Mapping[str, float], after: Mapping[str, float]) -> list[str]:
    """Return one line per task whose pass@1 fell, or that disappeared."""
    lines: list[str] = []
    for task_id in sorted(set(before) | set(after)):
        old = before.get(task_id)
        new = after.get(task_id)
        if old is None and new is not None:
            lines.append(f"{task_id}: added at {new:.2f}")
        elif new is None and old is not None:
            lines.append(f"{task_id}: removed, was {old:.2f}")
        elif old is not None and new is not None and new < old:
            lines.append(f"{task_id}: {old:.2f} -> {new:.2f}")
    return lines
