"""Grade one trial: state, side effects, assertions, and a failure tag.

``passed`` requires a finished agent, a matching database, and no failed
assertion. The failure tag is the first rule that fits.

Example:
    from agentgauntlet.grading import grade_trial

    grade = grade_trial(task, steps, "completed", "done", before, after)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from agentgauntlet.agents.base import StepRecord
from agentgauntlet.grading.assertions import AssertionFailure, check_assertions
from agentgauntlet.grading.metrics import TrialObservation
from agentgauntlet.grading.state_diff import Snapshot, diff_state
from agentgauntlet.runner.sandbox import domain_for
from agentgauntlet.runner.trajectory import (
    TrialStatus,
    database_path,
    read_result,
    read_steps,
    template_path,
    trial_path,
)
from agentgauntlet.tasks.schema import Task

FailureTag = Literal[
    "wrong_tool",
    "wrong_args",
    "policy_violation",
    "gave_up",
    "hallucinated_success",
    "step_limit",
    "tool_error_not_recovered",
]


def grade_trial(
    task: Task,
    steps: list[StepRecord],
    status: TrialStatus,
    final_answer: str,
    before: Snapshot,
    after: Snapshot,
    *,
    trial: int = 0,
) -> TrialObservation:
    """Grade one finished attempt. The failure field is set only when it failed."""
    called = [step.tool for step in steps if step.kind == "tool" and step.tool is not None]
    state = diff_state(before, after, task.expected_state)
    failures = check_assertions(task, called, final_answer, before, after)
    passed = status == "completed" and state.ok and not failures
    tag = None if passed else _classify(task, steps, status, state.ok, failures)
    tokens = [step.tokens for step in steps if step.tokens is not None]
    costs = [step.cost_usd for step in steps if step.cost_usd is not None]
    return TrialObservation(
        task_id=task.id,
        trial=trial,
        passed=passed,
        failure=tag,
        latency_ms=sum(step.latency_ms or 0.0 for step in steps),
        tokens=sum(tokens) if tokens else None,
        cost_usd=sum(costs) if costs else None,
        tool_calls=len(called),
    )


def grade_run(tasks: list[Task], runs_dir: Path, run_id: str) -> list[TrialObservation]:
    """Grade every finished trial under ``runs_dir/run_id``."""
    observations: list[TrialObservation] = []
    for task in tasks:
        template = template_path(runs_dir, run_id, task.id)
        if not template.is_file():
            continue
        before = domain_for(task.domain, template, seed=task.seed).snapshot()
        trial = 0
        while True:
            path = trial_path(runs_dir, run_id, task.id, trial)
            result = read_result(path)
            if result is None:
                break
            after = domain_for(
                task.domain,
                database_path(runs_dir, run_id, task.id, trial),
                seed=task.seed,
            ).snapshot()
            observations.append(
                grade_trial(
                    task,
                    read_steps(path),
                    result.status,
                    result.final_answer,
                    before,
                    after,
                    trial=trial,
                )
            )
            trial += 1
    return observations


def _classify(
    task: Task,
    steps: list[StepRecord],
    status: TrialStatus,
    state_ok: bool,
    failures: list[AssertionFailure],
) -> FailureTag:
    if status == "step_limit":
        return "step_limit"
    if status in {"timeout", "error"}:
        return "gave_up"
    if any(failure.kind == "tool_not_called" for failure in failures):
        return "policy_violation"
    if _unrecovered_tool_error(steps):
        return "tool_error_not_recovered"
    if _wrong_args(task, steps):
        return "wrong_args"
    if _unknown_tool(task, steps):
        return "wrong_tool"
    if status == "completed" and not state_ok:
        return "hallucinated_success"
    return "wrong_tool"


def _unrecovered_tool_error(steps: list[StepRecord]) -> bool:
    failed: set[str] = set()
    for step in steps:
        if step.kind != "tool" or step.tool is None:
            continue
        if step.is_error and step.expect_error is None:
            failed.add(step.tool)
        elif not step.is_error:
            failed.discard(step.tool)
    return bool(failed)


def _wrong_args(task: Task, steps: list[StepRecord]) -> bool:
    reference: dict[str, list[dict[str, object]]] = {}
    for call in task.reference_solution.tool_calls:
        reference.setdefault(call.tool, []).append(dict(call.arguments))
    for step in steps:
        if step.kind != "tool" or step.tool is None or step.tool not in reference:
            continue
        if dict(step.arguments or {}) not in reference[step.tool]:
            return True
    return False


def _unknown_tool(task: Task, steps: list[StepRecord]) -> bool:
    known = {call.tool for call in task.reference_solution.tool_calls}
    return any(
        step.kind == "tool" and step.tool is not None and step.tool not in known for step in steps
    )
