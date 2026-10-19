"""pass@1, pass^k, consistency, cost, and a bootstrap confidence interval.

pass^k uses the unbiased estimator from τ-bench: with ``c`` successes in ``n``
trials, pass^k is ``C(c, k) / C(n, k)``. Consistency is ``1`` minus the
population variance of the 0/1 outcomes. The 95% interval resamples tasks, not
trials, and reads the 2.5 and 97.5 linear percentiles.

Example:
    from agentgauntlet.grading import pass_hat_k

    pass_hat_k(successes=3, trials=5, k=2)
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from agentgauntlet.tasks.schema import Task

KS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class TrialObservation:
    """The fields a metric needs from one graded trial."""

    task_id: str
    passed: bool
    failure: str | None
    latency_ms: float
    tokens: int | None
    cost_usd: float | None
    tool_calls: int
    trial: int = 0


@dataclass(frozen=True)
class NumberSummary:
    """Mean, median, and 95th percentile. Empty input leaves all three unset."""

    mean: float | None
    median: float | None
    p95: float | None


@dataclass(frozen=True)
class TaskScore:
    """Metrics for one task."""

    task_id: str
    domain: str
    difficulty: str
    successes: int
    trials: int
    pass_at_1: float
    pass_hat: dict[int, float]
    consistency: float
    latency: NumberSummary
    tokens: NumberSummary
    cost: NumberSummary
    tool_calls: NumberSummary
    total_cost: float
    cost_per_success: float | None
    failures: dict[str, int]


@dataclass(frozen=True)
class SliceScore:
    """Metrics for a set of tasks. Each task has equal weight."""

    name: str
    tasks: int
    pass_at_1: float
    pass_hat: dict[int, float]
    consistency: float
    cost_per_success: float | None
    failures: dict[str, int]


@dataclass(frozen=True)
class BenchmarkScore:
    """Per-task scores plus overall, domain, and difficulty slices."""

    tasks: list[TaskScore]
    overall: SliceScore
    by_domain: list[SliceScore]
    by_difficulty: list[SliceScore]
    pass_at_1_interval: tuple[float, float]


def pass_hat_k(successes: int, trials: int, k: int) -> float:
    """Return ``C(successes, k) / C(trials, k)``, or 0 when that is impossible."""
    if k < 1 or k > trials or k > successes:
        return 0.0
    return math.comb(successes, k) / math.comb(trials, k)


def consistency(outcomes: Sequence[int]) -> float:
    """Return ``1 - population variance`` of 0/1 trial outcomes.

    An empty list is consistent. So is a list of all failures: the variance of
    a constant is zero.
    """
    if not outcomes:
        return 1.0
    mean = sum(outcomes) / len(outcomes)
    variance = sum((value - mean) ** 2 for value in outcomes) / len(outcomes)
    return 1.0 - variance


def summarize_numbers(values: Sequence[float]) -> NumberSummary:
    """Summarize a sample. The 95th percentile interpolates on ``(n - 1)``."""
    if not values:
        return NumberSummary(mean=None, median=None, p95=None)
    ordered = sorted(values)
    return NumberSummary(
        mean=sum(ordered) / len(ordered),
        median=_median(ordered),
        p95=_percentile(ordered, 0.95),
    )


def percentile_interval(
    samples: Sequence[float],
    *,
    low: float = 0.025,
    high: float = 0.975,
) -> tuple[float, float]:
    """Return the linear percentiles of ``samples``."""
    ordered = sorted(samples)
    return _percentile(ordered, low), _percentile(ordered, high)


def bootstrap_means(values: Sequence[float], resamples: Sequence[Sequence[int]]) -> list[float]:
    """Return the mean of ``values`` at each list of indexes."""
    means: list[float] = []
    for indexes in resamples:
        draw = [values[index] for index in indexes]
        means.append(sum(draw) / len(draw))
    return means


def bootstrap_ci(
    values: Sequence[float],
    *,
    samples: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """Bootstrap a 95% interval for the mean of ``values`` by resampling tasks."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)  # noqa: S311
    width = len(values)
    resamples = [[rng.randrange(width) for _ in range(width)] for _ in range(samples)]
    return percentile_interval(bootstrap_means(values, resamples))


def score_benchmark(
    tasks: Sequence[Task],
    observations: Sequence[TrialObservation],
    *,
    ks: Sequence[int] = KS,
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 0,
) -> BenchmarkScore:
    """Score every task, then average tasks within each slice."""
    known = {task.id: task for task in tasks}
    grouped: dict[str, list[TrialObservation]] = defaultdict(list)
    for observation in observations:
        if observation.task_id not in known:
            raise ValueError(f"no task named {observation.task_id}")
        grouped[observation.task_id].append(observation)
    scored = [_score_task(known[task_id], trials, ks) for task_id, trials in grouped.items()]
    scored.sort(key=lambda item: item.task_id)
    overall = _slice("overall", scored)
    return BenchmarkScore(
        tasks=scored,
        overall=overall,
        by_domain=_slices(scored, "domain"),
        by_difficulty=_slices(scored, "difficulty"),
        pass_at_1_interval=bootstrap_ci(
            [item.pass_at_1 for item in scored],
            samples=bootstrap_samples,
            seed=bootstrap_seed,
        ),
    )


def _score_task(task: Task, trials: Sequence[TrialObservation], ks: Sequence[int]) -> TaskScore:
    outcomes = [1 if trial.passed else 0 for trial in trials]
    successes = sum(outcomes)
    count = len(trials)
    costs = [trial.cost_usd for trial in trials if trial.cost_usd is not None]
    total_cost = sum(costs)
    tokens = [float(trial.tokens) for trial in trials if trial.tokens is not None]
    failures = Counter(trial.failure for trial in trials if trial.failure is not None)
    return TaskScore(
        task_id=task.id,
        domain=task.domain,
        difficulty=task.difficulty,
        successes=successes,
        trials=count,
        pass_at_1=successes / count if count else 0.0,
        pass_hat={k: pass_hat_k(successes, count, k) for k in ks},
        consistency=consistency(outcomes),
        latency=summarize_numbers([trial.latency_ms for trial in trials]),
        tokens=summarize_numbers(tokens),
        cost=summarize_numbers(costs),
        tool_calls=summarize_numbers([float(trial.tool_calls) for trial in trials]),
        total_cost=total_cost,
        cost_per_success=(total_cost / successes) if successes else None,
        failures=dict(failures),
    )


def _slices(scored: Sequence[TaskScore], field: str) -> list[SliceScore]:
    grouped: dict[str, list[TaskScore]] = defaultdict(list)
    for item in scored:
        grouped[str(getattr(item, field))].append(item)
    return [_slice(name, grouped[name]) for name in sorted(grouped)]


def _slice(name: str, scored: Sequence[TaskScore]) -> SliceScore:
    if not scored:
        return SliceScore(name, 0, 0.0, {}, 1.0, None, {})
    count = len(scored)
    keys = sorted({key for item in scored for key in item.pass_hat})
    successes = sum(item.successes for item in scored)
    total_cost = sum(item.total_cost for item in scored)
    failures: Counter[str] = Counter()
    for item in scored:
        failures.update(item.failures)
    return SliceScore(
        name=name,
        tasks=count,
        pass_at_1=sum(item.pass_at_1 for item in scored) / count,
        pass_hat={key: sum(item.pass_hat[key] for item in scored) / count for key in keys},
        consistency=sum(item.consistency for item in scored) / count,
        cost_per_success=(total_cost / successes) if successes else None,
        failures=dict(failures),
    )


def _median(ordered: Sequence[float]) -> float:
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _percentile(ordered: Sequence[float], p: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    index = p * (len(ordered) - 1)
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    weight = index - low
    return ordered[low] * (1 - weight) + ordered[high] * weight
