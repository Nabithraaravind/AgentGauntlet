"""Run tasks for k trials and write a JSONL trajectory for each one.

Trials of one task share a template database and each get a copy. A finished
trajectory is skipped, so a stopped run can be started again.

Example:
    from agentgauntlet.agents import ScriptedAgent
    from agentgauntlet.runner import RunConfig, run_benchmark
    from agentgauntlet.tasks import load_tasks

    summary = await run_benchmark(
        [task for task in load_tasks() if task.id == "retail-001"],
        ScriptedAgent(),
        RunConfig(run_id="demo", k=1),
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from mcp import Client
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentgauntlet.agents.base import Action, Agent, StepRecord
from agentgauntlet.agents.mcp_client import ToolSession, ToolSpec
from agentgauntlet.runner.sandbox import (
    UnknownDomainError,
    clone_database,
    domain_for,
    materialize_world,
)
from agentgauntlet.runner.trajectory import (
    TrialHeader,
    TrialResult,
    TrialStatus,
    database_path,
    read_status,
    template_path,
    trial_path,
    write_trajectory,
)
from agentgauntlet.security.guardrails import Guardrail, policy_allows, present
from agentgauntlet.security.injections import attack_by_id, inject
from agentgauntlet.tasks.schema import Task

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class RunConfig(BaseModel):
    """Knobs for one benchmark run.

    ``k`` is the number of trials per task. ``tool_retries`` is how many extra
    attempts a retryable tool error gets. It defaults to zero so a scripted
    failure stays visible.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    runs_dir: Path = Path("runs")
    k: int = Field(default=5, ge=1)
    concurrency: int = Field(default=4, ge=1)
    timeout_seconds: float = Field(default=60, gt=0)
    tool_retries: int = Field(default=0, ge=0)
    attack: str | None = None
    guardrail: Guardrail = "none"

    @model_validator(mode="after")
    def safe_run_id(self) -> Self:
        """Reject a run id that is not a single path segment."""
        if _RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError(f"run_id {self.run_id!r} is not a safe directory name")
        return self


class TrialOutcome(BaseModel):
    """One finished or skipped trial."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    trial: int
    status: TrialStatus
    skipped: bool
    path: Path


class RunSummary(BaseModel):
    """Every trial the runner considered, in task order then trial order."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    trials: list[TrialOutcome]

    @property
    def completed(self) -> int:
        """How many trials reached a final answer, including ones resumed as done."""
        return sum(1 for trial in self.trials if trial.status == "completed")


async def run_benchmark(
    tasks: list[Task],
    agent: Agent,
    config: RunConfig,
    *,
    on_trial: Callable[[TrialOutcome], None] | None = None,
) -> RunSummary:
    """Run ``tasks`` for ``config.k`` trials and return one outcome per trial."""
    if config.attack is not None:
        attack_by_id(config.attack)
    _write_manifest(config, agent, [task.id for task in tasks])
    templates = {task.id: _template(config, task) for task in tasks}
    semaphore = asyncio.Semaphore(config.concurrency)
    jobs = [
        _execute(task, trial, templates[task.id], agent, config, semaphore, on_trial)
        for task in tasks
        for trial in range(config.k)
    ]
    trials = list(await asyncio.gather(*jobs))
    return RunSummary(run_id=config.run_id, trials=trials)


async def _execute(
    task: Task,
    trial: int,
    template: Path | None,
    agent: Agent,
    config: RunConfig,
    semaphore: asyncio.Semaphore,
    on_trial: Callable[[TrialOutcome], None] | None,
) -> TrialOutcome:
    async with semaphore:
        outcome = await _execute_one(task, trial, template, agent, config)
    if on_trial is not None:
        on_trial(outcome)
    return outcome


async def _execute_one(
    task: Task,
    trial: int,
    template: Path | None,
    agent: Agent,
    config: RunConfig,
) -> TrialOutcome:
    path = trial_path(config.runs_dir, config.run_id, task.id, trial)
    existing = read_status(path)
    if existing is not None:
        return TrialOutcome(task_id=task.id, trial=trial, status=existing, skipped=True, path=path)
    if template is None:
        return _finish(
            config,
            task,
            trial,
            agent.name,
            [],
            [],
            "error",
            "",
            f"domain {task.domain!r} has no world yet",
        )
    database = database_path(config.runs_dir, config.run_id, task.id, trial)
    clone_database(template, database)
    world = domain_for(task.domain, database, seed=task.seed)
    server = world.mcp_server()
    logging.getLogger("mcp.server.mcpserver.server").setLevel(logging.WARNING)
    steps: list[StepRecord] = []
    tools: list[str] = []
    status: TrialStatus = "error"
    final_answer = ""
    error: str | None = "trial stopped"
    try:
        async with Client(server, raise_exceptions=True) as client:
            session = ToolSession(client, retries=config.tool_retries)
            specs = await session.list_tool_specs()
            tools = [spec.name for spec in specs]
            status, final_answer, error = await _drive(task, agent, session, steps, specs, config)
    except Exception as exc:
        status = "error"
        error = _error_text(exc)
    return _finish(config, task, trial, agent.name, tools, steps, status, final_answer, error)


async def _drive(
    task: Task,
    agent: Agent,
    session: ToolSession,
    steps: list[StepRecord],
    specs: list[ToolSpec],
    config: RunConfig,
) -> tuple[TrialStatus, str, str | None]:
    deadline = time.monotonic() + config.timeout_seconds
    _append_message(steps, "user", task.user_goal)
    attack = None if config.attack is None else attack_by_id(config.attack)
    injected = False
    tool_count = 0
    while True:
        try:
            action = await asyncio.wait_for(
                agent.act(task, steps, specs),
                timeout=deadline - time.monotonic(),
            )
        except TimeoutError:
            return "timeout", "", "trial timed out"
        if action.final_answer is not None:
            _append_message(steps, "assistant", action.final_answer, action)
            return "completed", action.final_answer, None
        if tool_count >= task.max_steps:
            return "step_limit", "", f"stopped after {task.max_steps} tool calls"
        tool_name = action.tool
        if tool_name is None:
            return "error", "", "action has neither a tool nor a final answer"
        if config.guardrail == "policy" and not policy_allows(
            tool_name, action.arguments, task.user_goal
        ):
            _append_blocked(steps, action, tool_name)
            tool_count += 1
            continue
        try:
            outcome = await asyncio.wait_for(
                session.call(tool_name, action.arguments),
                timeout=deadline - time.monotonic(),
            )
        except TimeoutError:
            return "timeout", "", "trial timed out"
        text = outcome.text
        if attack is not None and not injected and not outcome.is_error:
            text = inject(text, attack)
            injected = True
        text = present(text, config.guardrail)
        steps.append(
            StepRecord(
                index=len(steps),
                kind="tool",
                role="tool",
                tool=outcome.tool,
                arguments=outcome.arguments,
                is_error=outcome.is_error,
                expect_error=action.expect_error,
                text=text,
                latency_ms=outcome.latency_ms + (action.latency_ms or 0),
                attempts=outcome.attempts,
                tokens=_tokens(action),
                cost_usd=action.cost_usd,
            )
        )
        tool_count += 1


def _append_blocked(steps: list[StepRecord], action: Action, tool_name: str) -> None:
    steps.append(
        StepRecord(
            index=len(steps),
            kind="tool",
            role="tool",
            tool=tool_name,
            arguments=dict(action.arguments),
            is_error=True,
            expect_error=action.expect_error,
            text="policy: this write is not asked for by the user goal",
            latency_ms=action.latency_ms or 0,
            attempts=1,
            tokens=_tokens(action),
            cost_usd=action.cost_usd,
        )
    )


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_error_text(item) for item in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"


def _append_message(
    steps: list[StepRecord],
    role: Literal["user", "assistant"],
    text: str,
    action: Action | None = None,
) -> None:
    steps.append(
        StepRecord(
            index=len(steps),
            kind="message",
            role=role,
            text=text,
            tokens=None if action is None else _tokens(action),
            cost_usd=None if action is None else action.cost_usd,
            latency_ms=None if action is None else action.latency_ms,
        )
    )


def _tokens(action: Action) -> int | None:
    if action.prompt_tokens is None and action.completion_tokens is None:
        return None
    return (action.prompt_tokens or 0) + (action.completion_tokens or 0)


def _finish(
    config: RunConfig,
    task: Task,
    trial: int,
    agent_name: str,
    tools: list[str],
    steps: list[StepRecord],
    status: TrialStatus,
    final_answer: str,
    error: str | None,
) -> TrialOutcome:
    path = trial_path(config.runs_dir, config.run_id, task.id, trial)
    tool_calls = sum(1 for step in steps if step.kind == "tool")
    write_trajectory(
        path,
        TrialHeader(
            run_id=config.run_id,
            task_id=task.id,
            trial=trial,
            seed=task.seed,
            agent=agent_name,
            domain=task.domain,
            tools=tools,
        ),
        steps,
        TrialResult(
            status=status,
            final_answer=final_answer,
            tool_calls=tool_calls,
            error=error,
        ),
    )
    return TrialOutcome(task_id=task.id, trial=trial, status=status, skipped=False, path=path)


def _template(config: RunConfig, task: Task) -> Path | None:
    try:
        path = template_path(config.runs_dir, config.run_id, task.id)
        materialize_world(task.domain, path, seed=task.seed)
    except UnknownDomainError:
        return None
    return path


def _write_manifest(config: RunConfig, agent: Agent, task_ids: list[str]) -> None:
    directory = config.runs_dir / config.run_id
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "run_id": config.run_id,
        "agent": agent.name,
        "k": config.k,
        "tasks": task_ids,
    }
    model = getattr(agent, "model", None)
    if isinstance(model, str):
        payload["model"] = model
    if config.attack is not None:
        payload["attack"] = config.attack
        payload["guardrail"] = config.guardrail
    text = json.dumps(payload, indent=2) + "\n"
    (directory / "manifest.json").write_text(text, encoding="utf-8", newline="\n")


def format_summary(summary: RunSummary) -> str:
    """Return one line describing how many trials finished."""
    skipped = sum(1 for trial in summary.trials if trial.skipped)
    ran = len(summary.trials) - skipped
    return (
        f"run {summary.run_id}: {len(summary.trials)} trials, "
        f"{summary.completed} completed, {ran} ran, {skipped} skipped"
    )


# Imported for tests that want the completeness check without reaching into trajectory.
__all__ = ["RunConfig", "RunSummary", "TrialOutcome", "format_summary", "run_benchmark"]
