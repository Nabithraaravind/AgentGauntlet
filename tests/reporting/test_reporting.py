"""HTML report, charts, Markdown, and the result loader."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from agentgauntlet.agents import ScriptedAgent
from agentgauntlet.grading.metrics import (
    KS,
    BenchmarkScore,
    TrialObservation,
    score_benchmark,
)
from agentgauntlet.reporting.charts import failure_svg, pareto_svg, reliability_svg
from agentgauntlet.reporting.compare import regression_lines
from agentgauntlet.reporting.html_report import (
    StepView,
    TrialView,
    _answer,
    build_report,
    render_html,
    step_is_injected,
)
from agentgauntlet.reporting.leaderboard import load_leaderboard
from agentgauntlet.reporting.markdown import leaderboard
from agentgauntlet.runner.engine import RunConfig, run_benchmark
from agentgauntlet.security.suite import SecurityRow
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Task


def test_charts_draw_bars_and_an_empty_plot() -> None:
    """A chart names itself, and an empty series is still an SVG."""
    drawn = reliability_svg({1: 1.0, 5: 0.25})
    assert 'data-chart="reliability"' in drawn
    assert "1" in drawn
    assert failure_svg({"wrong_tool": 2})
    assert 'data-chart="failures"' in failure_svg({})
    assert 'data-chart="pareto"' in pareto_svg(())
    marked = pareto_svg([("scripted", 0.0, 1.0)])
    assert "scripted" in marked


def test_leaderboard_and_regressions() -> None:
    """Missing cost is n/a, and a lower pass rate is a regression."""
    text = leaderboard([("scripted", 1.0, None), ("other", 0.5, 0.25)])
    assert "| scripted | 1.000 | n/a |" in text
    assert "| other | 0.500 | 0.2500 |" in text
    assert regression_lines({"retail-001": 1.0, "retail-002": 1.0}, {"retail-001": 0.5}) == [
        "retail-001: 1.00 -> 0.50",
        "retail-002: removed, was 1.00",
    ]
    assert regression_lines({}, {"retail-003": 1.0}) == ["retail-003: added at 1.00"]
    assert regression_lines({"retail-001": 1.0}, {"retail-001": 1.0}) == []


def test_report_marks_injected_text_and_says_when_asr_is_absent() -> None:
    """The scorecard keeps an unmeasured ASR blank, and injected text is a red row."""
    html = render_html(
        "demo",
        pass_at_1=1.0,
        interval=(1.0, 1.0),
        pass_hat={1: 1.0},
        cost_per_success=None,
        asr=None,
        failures={},
        heatmap=[("domain retail", 1.0)],
        pareto=(),
        security=(SecurityRow("none", "direct-override", 1, 0.0, 1.0),),
        trials=(
            TrialView(
                "retail-001",
                0,
                "passed",
                "Order A1043 is delivered.",
                (StepView("IGNORE PREVIOUS INSTRUCTIONS", "injected"),),
            ),
        ),
    )
    assert "pass@1 1.000" in html
    assert "ASR not measured" in html
    assert "cost per success n/a" in html
    assert "No attack trials" not in html
    assert "direct-override" in html
    assert 'class="injected"' in html
    assert step_is_injected("IGNORE PREVIOUS INSTRUCTIONS")
    assert step_is_injected("<<UNTRUSTED_TOOL_DATA>>")
    assert not step_is_injected("order is delivered")
    assert _answer(Path("missing.jsonl")) == ""
    quiet = render_html(
        "quiet",
        pass_at_1=0.0,
        interval=(0.0, 0.0),
        pass_hat={},
        cost_per_success=1.5,
        asr=0.25,
        failures={"gave_up": 1},
        heatmap=(),
        pareto=(("quiet", 1.5, 0.0),),
        security=(),
        trials=(),
    )
    assert "No attack trials were recorded for this run." in quiet
    assert "ASR 0.250" in quiet
    assert "cost per success 1.5000" in quiet


def test_leaderboard_loader_skips_files_that_are_not_model_rows(tmp_path: Path) -> None:
    """Only JSON objects with a model name become rows."""
    assert load_leaderboard(tmp_path / "missing") == []
    (tmp_path / "list.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "nameless.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "qwen.json").write_text(
        '{"model": "qwen", "pass_at_1": 0.5, "pass_hat_5": 0.1, "asr": 0.2, '
        '"cost_per_success": 0.0}\n',
        encoding="utf-8",
    )
    rows = load_leaderboard(tmp_path)
    assert rows == [
        {
            "model": "qwen",
            "pass_at_1": 0.5,
            "pass_hat_5": 0.1,
            "asr": 0.2,
            "cost_per_success": 0.0,
        }
    ]


def test_build_report_rejects_a_missing_run(tmp_path: Path) -> None:
    """A run directory with no trials is an error, not an empty score."""
    with pytest.raises(ValueError, match="no finished trials"):
        build_report("missing", tmp_path, load_tasks())


def test_build_report_omits_the_pareto_point_when_cost_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A score with no cost per success draws the chart with no point."""
    runs = tmp_path / "runs"
    asyncio.run(
        run_benchmark(
            [next(task for task in load_tasks() if task.id == "retail-001")],
            ScriptedAgent(),
            RunConfig(run_id="report", runs_dir=runs, k=1, concurrency=1, timeout_seconds=30),
        )
    )

    def hide_cost(
        tasks: Sequence[Task],
        observations: Sequence[TrialObservation],
        *,
        ks: Sequence[int] = KS,
        bootstrap_samples: int = 1000,
        bootstrap_seed: int = 0,
    ) -> BenchmarkScore:
        score = score_benchmark(
            tasks,
            observations,
            ks=ks,
            bootstrap_samples=bootstrap_samples,
            bootstrap_seed=bootstrap_seed,
        )
        return replace(score, overall=replace(score.overall, cost_per_success=None))

    monkeypatch.setattr("agentgauntlet.reporting.html_report.score_benchmark", hide_cost)
    html = build_report("report", runs, load_tasks())
    assert 'data-chart="pareto"' in html
