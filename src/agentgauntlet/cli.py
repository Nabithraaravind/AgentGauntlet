# Typer stores its option objects in the parameter defaults. B008 flags that pattern.
# ruff: noqa: B008

"""Typer commands: list, run, report, replay, compare, and init.

``gauntlet run`` defaults to the scripted agent so a checkout works without a
model. ``--agent react`` calls LiteLLM.

Example:
    gauntlet list tasks --domain retail
    gauntlet run --tasks retail-001 --k 1 --run-id smoke
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer
from rich.progress import Progress

from agentgauntlet.agents import ReactAgent, ScriptedAgent
from agentgauntlet.agents.base import Agent
from agentgauntlet.gate import SAMPLE_CONFIG
from agentgauntlet.grading.grade import grade_run
from agentgauntlet.grading.metrics import score_benchmark
from agentgauntlet.reporting.compare import regression_lines
from agentgauntlet.reporting.html_report import build_report
from agentgauntlet.reporting.markdown import leaderboard
from agentgauntlet.runner.engine import RunConfig, TrialOutcome, format_summary, run_benchmark
from agentgauntlet.runner.trajectory import read_result, read_steps
from agentgauntlet.security.guardrails import Guardrail
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Task

app = typer.Typer(add_completion=False, no_args_is_help=True)
_DOMAINS = {"retail", "travel", "calendar_email", "banking"}


def main() -> None:
    """Console-script entry point."""
    app()


@app.command("list")
def list_tasks(
    kind: str = typer.Argument(help="Only 'tasks' is supported."),
    domain: str | None = typer.Option(None, "--domain"),
) -> None:
    """Print task ids, optionally for one domain."""
    if kind != "tasks":
        sys.stderr.write(f"unknown list {kind}\n")
        raise typer.Exit(1)
    tasks = load_tasks()
    if domain is not None:
        tasks = [task for task in tasks if task.domain == domain]
    sys.stdout.write("".join(f"{task.id}\n" for task in tasks))


@app.command("init")
def init(path: Path = typer.Argument(Path("gauntlet.yaml"))) -> None:
    """Write a starter gate file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SAMPLE_CONFIG, encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {path}\n")


@app.command("run")
def run(
    run_id: str = typer.Option("scripted", "--run-id"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    tasks: str = typer.Option("retail-001", "--tasks"),
    k: int = typer.Option(1, "--k"),
    agent: str = typer.Option("scripted", "--agent"),
    model: str = typer.Option("ollama/qwen2.5:7b-instruct", "--model"),
    attack: str | None = typer.Option(None, "--attack"),
    guardrail: Guardrail = typer.Option("none", "--guardrail"),
    timeout: float = typer.Option(60, "--timeout"),
) -> None:
    """Run tasks and write JSONL trajectories."""
    raise typer.Exit(
        asyncio.run(
            _run(
                run_id=run_id,
                runs_dir=runs_dir,
                tasks=tasks,
                k=k,
                agent_name=agent,
                model=model,
                attack=attack,
                guardrail=guardrail,
                timeout_seconds=timeout,
            )
        )
    )


@app.command("report")
def report(
    run_dir: Path = typer.Argument(help="A directory such as runs/smoke."),
    html: bool = typer.Option(False, "--html"),
    markdown: bool = typer.Option(False, "--markdown"),
) -> None:
    """Write an HTML report, a Markdown score line, or both."""
    if not html and not markdown:
        html = True
    if markdown:
        sys.stdout.write(_markdown_score(run_dir))
    if html:
        try:
            body = build_report(run_dir.name, run_dir.parent, load_tasks())
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            raise typer.Exit(1) from exc
        dest = run_dir / "report.html"
        dest.write_text(body, encoding="utf-8", newline="\n")
        sys.stdout.write(f"wrote {dest}\n")


@app.command("replay")
def replay(
    run_dir: Path = typer.Argument(),
    task_id: str = typer.Argument(),
    trial: int = typer.Option(0, "--trial"),
) -> None:
    """Print one trajectory."""
    path = run_dir / task_id / f"trial-{trial:02d}.jsonl"
    result = read_result(path)
    if result is None:
        sys.stderr.write(f"no finished trial at {path}\n")
        raise typer.Exit(1)
    lines = [f"{task_id} trial {trial}: {result.status}", result.final_answer]
    for step in read_steps(path):
        if step.kind == "tool":
            lines.append(f"{step.tool} {step.arguments}")
        elif step.text:
            lines.append(step.text)
    sys.stdout.write("\n".join(lines) + "\n")


@app.command("compare")
def compare(left: Path = typer.Argument(), right: Path = typer.Argument()) -> None:
    """Print tasks whose pass@1 fell from the left run to the right run."""
    try:
        text = format_compare(regression_lines(_rates(left), _rates(right)))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        raise typer.Exit(1) from exc
    sys.stdout.write(text)


def format_compare(lines: list[str]) -> str:
    """Render regression lines, or a single sentence when nothing fell."""
    if not lines:
        return "no regressions\n"
    return "\n".join(lines) + "\n"


def select_tasks(spec: str, tasks: list[Task]) -> list[Task]:
    """Return every task, one domain, or one id."""
    if spec == "all":
        return list(tasks)
    if spec in _DOMAINS:
        return [task for task in tasks if task.domain == spec]
    return [task for task in tasks if task.id == spec]


async def _run(
    *,
    run_id: str,
    runs_dir: Path,
    tasks: str,
    k: int,
    agent_name: str,
    model: str,
    attack: str | None,
    guardrail: Guardrail,
    timeout_seconds: float,
) -> int:
    selected = select_tasks(tasks, load_tasks())
    if not selected:
        sys.stderr.write(f"No tasks match {tasks}.\n")
        return 1
    if agent_name not in {"scripted", "react"}:
        sys.stderr.write(f"unknown agent {agent_name}\n")
        return 1
    try:
        config = RunConfig(
            run_id=run_id,
            runs_dir=runs_dir,
            k=k,
            concurrency=1,
            timeout_seconds=timeout_seconds,
            attack=attack,
            guardrail=guardrail,
        )
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    with Progress() as progress:
        bar = progress.add_task("trials", total=len(selected) * k)

        def advance(_outcome: TrialOutcome) -> None:
            progress.advance(bar)

        try:
            summary = await run_benchmark(
                selected,
                _agent(agent_name, model),
                config,
                on_trial=advance,
            )
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
    sys.stderr.write(format_summary(summary) + "\n")
    if all(trial.status == "completed" for trial in summary.trials):
        return 0
    return 1


def _agent(agent_name: str, model: str) -> Agent:
    if agent_name == "react":
        api_base = os.environ.get("OLLAMA_API_BASE")
        return ReactAgent(model, api_base=api_base or None)
    return ScriptedAgent()


def _markdown_score(run_dir: Path) -> str:
    try:
        rates = _rates(run_dir)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        raise typer.Exit(1) from exc
    score = sum(rates.values()) / len(rates) if rates else 0.0
    return leaderboard([(run_dir.name, score, None)])


def _rates(run_dir: Path) -> dict[str, float]:
    observations = grade_run(load_tasks(), run_dir.parent, run_dir.name)
    if not observations:
        raise ValueError(f"run {run_dir.name} has no finished trials")
    used = {item.task_id for item in observations}
    tasks = [task for task in load_tasks() if task.id in used]
    score = score_benchmark(tasks, observations, bootstrap_samples=20)
    return {item.task_id: item.pass_at_1 for item in score.tasks}
