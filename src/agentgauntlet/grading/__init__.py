"""State grading, assertion checks, and reliability metrics.

``grade_trial`` and ``grade_run`` are loaded on first use. Importing them from
here at startup would cycle through the task loader and the agent types.

Example:
    from agentgauntlet.grading import diff_state, pass_hat_k, score_benchmark

    pass_hat_k(successes=3, trials=5, k=2)
"""

from typing import TYPE_CHECKING

from agentgauntlet.grading.assertions import check_assertions
from agentgauntlet.grading.metrics import (
    TrialObservation,
    pass_hat_k,
    score_benchmark,
    summarize_numbers,
)
from agentgauntlet.grading.state_diff import StateDiff, diff_state, partial_match, values_equal

if TYPE_CHECKING:
    from agentgauntlet.grading.grade import grade_run as grade_run
    from agentgauntlet.grading.grade import grade_trial as grade_trial

__all__ = [
    "StateDiff",
    "TrialObservation",
    "check_assertions",
    "diff_state",
    "grade_run",
    "grade_trial",
    "partial_match",
    "pass_hat_k",
    "score_benchmark",
    "summarize_numbers",
    "values_equal",
]


def __getattr__(name: str) -> object:
    """Load the trial grader the first time a caller asks for it."""
    if name not in {"grade_run", "grade_trial"}:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    from agentgauntlet.grading import grade as grade_module

    value: object = getattr(grade_module, name)
    globals()[name] = value
    return value
