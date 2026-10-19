"""Hand-checked state diffs and pass^k figures."""

from __future__ import annotations

from pathlib import Path

import pytest

import agentgauntlet.grading as grading
from agentgauntlet.agents import ScriptedAgent, StepRecord
from agentgauntlet.grading import (
    diff_state,
    grade_run,
    grade_trial,
    pass_hat_k,
    score_benchmark,
    summarize_numbers,
)
from agentgauntlet.grading.metrics import (
    TrialObservation,
    bootstrap_means,
    consistency,
    percentile_interval,
)
from agentgauntlet.runner import RunConfig, run_benchmark
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Assertion, Task


def _task(task_id: str) -> Task:
    return next(task for task in load_tasks() if task.id == task_id)


def _tool(
    name: str,
    arguments: dict[str, str | int | float | bool | None],
    *,
    is_error: bool = False,
    latency_ms: float = 0,
    tokens: int | None = None,
    cost_usd: float | None = None,
) -> StepRecord:
    return StepRecord(
        index=0,
        kind="tool",
        role="tool",
        tool=name,
        arguments=arguments,
        is_error=is_error,
        text="",
        latency_ms=latency_ms,
        tokens=tokens,
        cost_usd=cost_usd,
    )


def test_state_diff_allows_expected_writes_and_flags_extras() -> None:
    """A covered update is fine. An extra refund, or a pure delete, is not."""
    before = {
        "orders": [
            {"id": "A1", "status": "placed"},
            {"id": "A2", "status": "placed"},
        ],
        "refunds": [],
    }
    cancelled = {
        "orders": [
            {"id": "A1", "status": "cancelled"},
            {"id": "A2", "status": "placed"},
        ],
        "refunds": [],
    }
    expected = {"orders": [{"id": "A1", "status": "cancelled"}]}
    assert diff_state(before, cancelled, expected).ok

    orders: list[dict[str, object]] = [
        {"id": "A1", "status": "cancelled"},
        {"id": "A2", "status": "placed"},
    ]
    refunds: list[dict[str, object]] = [{"order_id": "A9", "amount_inr": 1}]
    leaked = diff_state(before, {"orders": orders, "refunds": refunds}, expected)
    assert leaked.missing == []
    assert not leaked.ok
    assert any("refunds" in item for item in leaked.side_effects)

    both_changed = {
        "orders": [
            {"id": "A1", "status": "cancelled"},
            {"id": "A2", "status": "shipped"},
        ],
        "refunds": [],
    }
    spill = diff_state(before, both_changed, expected)
    assert any("A2" in item for item in spill.side_effects)

    duplicated = {
        "orders": [
            {"id": "A1", "status": "cancelled"},
            {"id": "A1", "status": "cancelled"},
        ],
        "refunds": [],
    }
    second = diff_state({"orders": [], "refunds": []}, duplicated, expected)
    assert any("unexpected write" in item for item in second.side_effects)

    deleted = diff_state(before, {"orders": [], "refunds": []}, {"orders": []})
    assert deleted.missing == []
    assert any("delete" in item for item in deleted.side_effects)

    absent = diff_state(before, before, {"orders": [{"id": "A9", "status": "missing"}]})
    assert absent.missing
    assert not absent.ok


def test_failure_tags_follow_a_fixed_priority() -> None:
    """The first matching rule wins, from step limit down to a false claim of success."""
    task = _task("retail-001").model_copy(
        update={
            "expected_state": {"orders": [{"id": "A1", "status": "open"}]},
            "assertions": [],
        }
    )
    same = {"orders": [{"id": "A1", "status": "open"}]}
    wrong = {"orders": [{"id": "A1", "status": "closed"}]}
    call = _tool("get_order", {"order_id": "A1043"})

    assert grade_trial(task, [call], "step_limit", "", same, same).failure == "step_limit"
    assert grade_trial(task, [], "timeout", "", same, same).failure == "gave_up"
    assert grade_trial(task, [], "error", "", same, same).failure == "gave_up"

    forbidden = task.model_copy(
        update={"assertions": [Assertion(type="tool_not_called", tool="get_order")]}
    )
    assert grade_trial(forbidden, [call], "completed", "done", same, same).failure == (
        "policy_violation"
    )

    broken = _tool("get_order", {"order_id": "A1043"}, is_error=True)
    assert grade_trial(task, [broken], "completed", "done", same, wrong).failure == (
        "tool_error_not_recovered"
    )
    recovered = grade_trial(task, [broken, call], "completed", "done", same, wrong)
    assert recovered.failure == "hallucinated_success"

    bad_args = _tool("get_order", {"order_id": "A0000"})
    planned_failure = StepRecord(
        index=1,
        kind="tool",
        role="tool",
        tool="get_order",
        arguments=None,
        is_error=True,
        expect_error="not_found",
        text="",
    )
    note = StepRecord(index=2, kind="message", role="user", text="hi")
    nameless = StepRecord(index=3, kind="tool", role="tool", tool=None, text="")
    assert (
        grade_trial(
            task, [note, planned_failure, nameless, bad_args], "completed", "done", same, wrong
        ).failure
        == "wrong_args"
    )

    other = _tool("explode", {})
    assert grade_trial(task, [other], "completed", "done", same, wrong).failure == "wrong_tool"

    picky = task.model_copy(
        update={"assertions": [Assertion(type="final_answer_contains", any_of=["done"])]}
    )
    assert grade_trial(picky, [call], "completed", "nope", same, same).failure == "wrong_tool"

    passed = grade_trial(
        task,
        [_tool("get_order", {"order_id": "A1043"}, latency_ms=4, tokens=3, cost_usd=0.25)],
        "completed",
        "done",
        same,
        same,
    )
    assert passed.passed
    assert passed.failure is None
    assert passed.latency_ms == 4
    assert passed.tokens == 3
    assert passed.cost_usd == 0.25


def test_pass_hat_k_and_consistency_match_hand_arithmetic() -> None:
    """3 successes in 5 trials, then a second task that succeeds every time.

    pass^k = C(c, k) / C(n, k):
    C(3, 1) / C(5, 1) = 3/5 = 0.6
    C(3, 2) / C(5, 2) = 3/10 = 0.3
    C(3, 3) / C(5, 3) = 1/10 = 0.1
    k > 3 is 0.

    Outcomes 1,1,1,0,0 have mean 0.6.
    Population variance is (3 * 0.4^2 + 2 * 0.6^2) / 5 = 1.2 / 5 = 0.24.
    Consistency is 1 - 0.24 = 0.76.
    The perfect task has pass^k 1 and consistency 1.
    Overall pass@1 is (0.6 + 1) / 2 = 0.8.
    Overall pass^2 is (0.3 + 1) / 2 = 0.65.
    Overall consistency is (0.76 + 1) / 2 = 0.88.
    Cost per success is (5 * 1 + 5 * 2) / (3 + 5) = 15/8 = 1.875.
    """
    assert pass_hat_k(3, 5, 1) == pytest.approx(0.6)
    assert pass_hat_k(3, 5, 2) == pytest.approx(0.3)
    assert pass_hat_k(3, 5, 3) == pytest.approx(0.1)
    assert pass_hat_k(3, 5, 4) == 0
    assert pass_hat_k(3, 5, 5) == 0
    assert consistency([1, 1, 1, 0, 0]) == pytest.approx(0.76)
    assert consistency([0, 0, 0]) == 1
    assert consistency([]) == 1

    easy = _observations("retail-001", [1, 1, 1, 0, 0], cost=1.0, failure="hallucinated_success")
    hard = _observations("retail-017", [1, 1, 1, 1, 1], cost=2.0, failure=None)
    score = score_benchmark([_task("retail-001"), _task("retail-017")], [*easy, *hard])
    first, second = score.tasks
    assert first.pass_at_1 == pytest.approx(0.6)
    assert first.pass_hat[2] == pytest.approx(0.3)
    assert first.consistency == pytest.approx(0.76)
    assert first.cost_per_success == pytest.approx(5 / 3)
    assert first.failures == {"hallucinated_success": 2}
    assert first.latency.mean == pytest.approx(40)
    assert first.latency.median == pytest.approx(30)
    assert first.latency.p95 == pytest.approx(88)
    assert second.pass_hat[5] == 1
    assert score.overall.pass_at_1 == pytest.approx(0.8)
    assert score.overall.pass_hat[2] == pytest.approx(0.65)
    assert score.overall.consistency == pytest.approx(0.88)
    assert score.overall.cost_per_success == pytest.approx(1.875)
    assert score.overall.failures == {"hallucinated_success": 2}
    by_difficulty = {item.name: item for item in score.by_difficulty}
    assert by_difficulty["easy"].pass_at_1 == pytest.approx(0.6)
    assert by_difficulty["hard"].pass_at_1 == 1
    assert score.by_domain[0].name == "retail"
    assert score.by_domain[0].pass_at_1 == pytest.approx(0.8)


def test_percentiles_and_bootstrap_use_the_linear_index() -> None:
    """Sorted samples 0, 0.5, 0.5, 1.

    The 2.5 percentile sits at 0.025 * 3 = 0.075, so 0 + 0.075 * 0.5 = 0.0375.
    The 97.5 percentile sits at 0.975 * 3 = 2.925, so 0.5 + 0.925 * 0.5 = 0.9625.
    Four resamples of tasks [0, 1] at indexes (0,0), (0,1), (1,0), (1,1)
    have means 0, 0.5, 0.5, 1.
    """
    low, high = percentile_interval([1, 0, 0.5, 0.5])
    assert low == pytest.approx(0.0375)
    assert high == pytest.approx(0.9625)
    assert percentile_interval([10.0, 40.0], low=0, high=1) == (10.0, 40.0)
    assert bootstrap_means([0.0, 1.0], [[0, 0], [0, 1], [1, 0], [1, 1]]) == [
        0.0,
        0.5,
        0.5,
        1.0,
    ]
    single = summarize_numbers([10])
    assert single.mean == 10
    assert single.median == 10
    assert single.p95 == 10
    even = summarize_numbers([10, 20, 30, 40])
    assert even.median == 25
    assert summarize_numbers([]).mean is None


def test_grading_package_rejects_unknown_names() -> None:
    """The lazy exports are the two graders, nothing else."""
    name = "not_a_grader"
    with pytest.raises(AttributeError, match="no attribute"):
        getattr(grading, name)


def test_score_rejects_an_unknown_task_and_an_empty_run() -> None:
    """A trial for a missing task is a caller bug. No trials score as zero."""
    with pytest.raises(ValueError, match="retail-999"):
        score_benchmark(
            [_task("retail-001")],
            [
                TrialObservation(
                    task_id="retail-999",
                    passed=False,
                    failure="gave_up",
                    latency_ms=0,
                    tokens=None,
                    cost_usd=None,
                    tool_calls=0,
                )
            ],
        )
    empty = score_benchmark([_task("retail-001")], [])
    assert empty.tasks == []
    assert empty.overall.tasks == 0
    assert empty.overall.pass_at_1 == 0
    assert empty.overall.pass_hat == {}
    assert empty.overall.cost_per_success is None
    assert empty.pass_at_1_interval == (0.0, 0.0)
    failed = _observations("retail-001", [0, 0, 0, 0, 0], cost=1.0, failure="gave_up")
    none_succeeded = score_benchmark([_task("retail-001")], failed)
    assert none_succeeded.tasks[0].cost_per_success is None
    assert none_succeeded.overall.cost_per_success is None


async def test_scripted_trial_grades_as_passed(tmp_path: Path) -> None:
    """A reference solution, played by the runner, passes state grading."""
    task = _task("retail-005")
    config = RunConfig(run_id="grade", runs_dir=tmp_path, k=1, concurrency=1, timeout_seconds=30)
    await run_benchmark([task], ScriptedAgent(), config)
    grades = grade_run([task], tmp_path, "grade")
    assert len(grades) == 1
    assert grades[0].passed
    assert grades[0].failure is None
    assert grades[0].tool_calls == 2
    score = score_benchmark([task], grades, bootstrap_samples=20)
    assert score.overall.pass_at_1 == 1
    assert score.tasks[0].pass_hat[2] == 0
    assert score.pass_at_1_interval == (1.0, 1.0)


def _observations(
    task_id: str,
    outcomes: list[int],
    *,
    cost: float,
    failure: str | None,
) -> list[TrialObservation]:
    latencies = [10.0, 20.0, 30.0, 40.0, 100.0]
    rows: list[TrialObservation] = []
    for index, outcome in enumerate(outcomes):
        rows.append(
            TrialObservation(
                task_id=task_id,
                trial=index,
                passed=outcome == 1,
                failure=None if outcome == 1 else failure,
                latency_ms=latencies[index],
                tokens=None,
                cost_usd=cost,
                tool_calls=1,
            )
        )
    return rows
