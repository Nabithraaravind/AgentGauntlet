"""Check the assertions stored on a task against one trajectory.

Example:
    from agentgauntlet.grading import check_assertions

    failures = check_assertions(task, called, final_answer, before, after)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentgauntlet.grading.state_diff import Snapshot

if TYPE_CHECKING:
    from agentgauntlet.tasks.schema import Task


@dataclass(frozen=True)
class AssertionFailure:
    """One assertion that the trajectory did not satisfy."""

    kind: str
    message: str


def check_assertions(
    task: Task,
    called: Sequence[str],
    final_answer: str,
    before: Snapshot,
    after: Snapshot,
) -> list[AssertionFailure]:
    """Return every assertion the trajectory missed."""
    failures: list[AssertionFailure] = []
    answer = final_answer.casefold()
    for assertion in task.assertions:
        tool = assertion.tool
        if assertion.type == "tool_not_called" and tool is not None and tool in called:
            failures.append(
                AssertionFailure("tool_not_called", f"{task.id}: called forbidden tool {tool}")
            )
        elif assertion.type == "tool_called" and tool is not None and tool not in called:
            failures.append(AssertionFailure("tool_called", f"{task.id}: never called {tool}"))
        elif (
            assertion.type == "max_tool_calls"
            and assertion.value is not None
            and len(called) > assertion.value
        ):
            failures.append(
                AssertionFailure(
                    "max_tool_calls",
                    f"{task.id}: used {len(called)} calls, max is {assertion.value}",
                )
            )
        elif assertion.type == "final_answer_contains":
            phrases = assertion.any_of or []
            if not any(phrase.casefold() in answer for phrase in phrases):
                failures.append(
                    AssertionFailure(
                        "final_answer_contains",
                        f"{task.id}: final answer does not contain any of {phrases}",
                    )
                )
        elif assertion.type == "table_unchanged" and assertion.table is not None:
            table = assertion.table
            if list(before.get(table, ())) != list(after.get(table, ())):
                failures.append(
                    AssertionFailure("table_unchanged", f"{task.id}: table {table} changed")
                )
    return failures
