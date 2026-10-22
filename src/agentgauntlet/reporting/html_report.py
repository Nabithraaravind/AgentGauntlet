"""Self-contained HTML report for one run.

Charts are inline SVG. Task sections include the final answer and each tool
result. Injected tool text is marked so it can be shown in red.

Example:
    from pathlib import Path

    from agentgauntlet.reporting.html_report import build_report
    from agentgauntlet.tasks import load_tasks

    html = build_report("demo", Path("runs"), load_tasks())
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from agentgauntlet.grading.grade import grade_run
from agentgauntlet.grading.metrics import score_benchmark
from agentgauntlet.reporting.charts import failure_svg, pareto_svg, reliability_svg
from agentgauntlet.runner.trajectory import read_result, read_steps, trial_path
from agentgauntlet.security.injections import ATTACKS
from agentgauntlet.security.suite import SecurityRow
from agentgauntlet.tasks.schema import Task

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AgentGauntlet {{ run_id }}</title>
<style>
body { font-family: Georgia, serif; margin: 2rem; color: #1c1917; }
.injected { color: #9b1c1c; font-weight: 700; }
table { border-collapse: collapse; margin: 1rem 0; }
td, th { border: 1px solid #d6d3d1; padding: 0.3rem 0.6rem; }
</style>
</head>
<body>
<h1>{{ run_id }}</h1>
<section id="scorecard">
<p>pass@1 {{ pass_at_1 }}</p>
<p>interval {{ interval_low }} to {{ interval_high }}</p>
<p>pass^5 {{ pass_hat_5 }}</p>
<p>cost per success {{ cost_label }}</p>
<p>ASR {{ asr_label }}</p>
</section>
<section id="reliability">{{ reliability_svg | safe }}</section>
<section id="pareto">{{ pareto_svg | safe }}</section>
<section id="failures">{{ failure_svg | safe }}</section>
<section id="heatmap">
<table>
{% for label, value in heatmap %}
<tr><td>{{ label }}</td><td>{{ value }}</td></tr>
{% endfor %}
</table>
</section>
<section id="security">
{% if security %}
<table>
{% for guardrail, category, asr, utility in security %}
<tr><td>{{ guardrail }}</td><td>{{ category }}</td><td>{{ asr }}</td><td>{{ utility }}</td></tr>
{% endfor %}
</table>
{% else %}
<p>No attack trials were recorded for this run.</p>
{% endif %}
</section>
<section id="tasks">
{% for trial in trials %}
<h2 id="{{ trial.task_id }}-{{ trial.trial }}">{{ trial.task_id }} trial {{ trial.trial }}</h2>
<p>{{ trial.outcome }}</p>
<p>{{ trial.final_answer }}</p>
<ul>
{% for step in trial.steps %}
<li class="{{ step.css }}">{{ step.text }}</li>
{% endfor %}
</ul>
{% endfor %}
</section>
</body>
</html>
"""


@dataclass(frozen=True)
class StepView:
    """One tool or message line in the report."""

    text: str
    css: str


@dataclass(frozen=True)
class TrialView:
    """One trial the report can scroll to."""

    task_id: str
    trial: int
    outcome: str
    final_answer: str
    steps: tuple[StepView, ...]


def _answer(path: Path) -> str:
    result = read_result(path)
    if result is None:
        return ""
    return result.final_answer


def step_is_injected(text: str) -> bool:
    """Return whether tool text still carries an attack trigger or a spotlight mark."""
    folded = text.casefold()
    if "<<untrusted_tool_data>>" in folded:
        return True
    return any(attack.trigger.casefold() in folded for attack in ATTACKS)


def render_html(
    run_id: str,
    *,
    pass_at_1: float,
    interval: tuple[float, float],
    pass_hat: dict[int, float],
    cost_per_success: float | None,
    asr: float | None,
    failures: dict[str, int],
    heatmap: Sequence[tuple[str, float]],
    pareto: Sequence[tuple[str, float, float]],
    security: Sequence[SecurityRow],
    trials: Sequence[TrialView],
) -> str:
    """Render the report body. Numbers are formatted here so the template stays simple."""
    environment = Environment(autoescape=True, undefined=StrictUndefined)
    template = environment.from_string(_TEMPLATE)
    return template.render(
        run_id=run_id,
        pass_at_1=f"{pass_at_1:.3f}",
        interval_low=f"{interval[0]:.3f}",
        interval_high=f"{interval[1]:.3f}",
        pass_hat_5=f"{pass_hat.get(5, 0.0):.3f}",
        cost_label="n/a" if cost_per_success is None else f"{cost_per_success:.4f}",
        asr_label="not measured" if asr is None else f"{asr:.3f}",
        reliability_svg=reliability_svg(pass_hat),
        pareto_svg=pareto_svg(pareto),
        failure_svg=failure_svg(failures),
        heatmap=[(label, f"{value:.3f}") for label, value in heatmap],
        security=[
            (row.guardrail, row.category, f"{row.asr:.2f}", f"{row.utility:.2f}")
            for row in security
        ],
        trials=trials,
    )


def build_report(run_id: str, runs_dir: Path, tasks: Sequence[Task]) -> str:
    """Grade ``run_id`` and return its HTML report."""
    observations = grade_run(list(tasks), runs_dir, run_id)
    used = [task for task in tasks if any(item.task_id == task.id for item in observations)]
    if not used:
        raise ValueError(f"run {run_id} has no finished trials")
    score = score_benchmark(used, observations, bootstrap_samples=200)
    views: list[TrialView] = []
    for item in observations:
        path = trial_path(runs_dir, run_id, item.task_id, item.trial)
        steps = tuple(
            StepView(step.text, "injected" if step_is_injected(step.text) else "")
            for step in read_steps(path)
        )
        views.append(
            TrialView(
                task_id=item.task_id,
                trial=item.trial,
                outcome="passed" if item.passed else "failed",
                final_answer=_answer(path),
                steps=steps,
            )
        )
    heatmap = [("domain " + item.name, item.pass_at_1) for item in score.by_domain]
    heatmap.extend(("difficulty " + item.name, item.pass_at_1) for item in score.by_difficulty)
    pareto: list[tuple[str, float, float]] = []
    if score.overall.cost_per_success is not None:
        pareto.append((run_id, score.overall.cost_per_success, score.overall.pass_at_1))
    return render_html(
        run_id,
        pass_at_1=score.overall.pass_at_1,
        interval=score.pass_at_1_interval,
        pass_hat=score.overall.pass_hat,
        cost_per_success=score.overall.cost_per_success,
        asr=None,
        failures=score.overall.failures,
        heatmap=heatmap,
        pareto=pareto,
        security=(),
        trials=views,
    )
