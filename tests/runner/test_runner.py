"""Scripted agent, isolated trials, and JSONL resume."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from agentgauntlet.agents import Action, ScriptedAgent, StepRecord
from agentgauntlet.agents.mcp_client import ToolSession, ToolSpec, message_text
from agentgauntlet.runner import RunConfig, RunSummary, TrialOutcome, run_benchmark
from agentgauntlet.runner.__main__ import main
from agentgauntlet.runner.engine import format_summary
from agentgauntlet.runner.sandbox import (
    UnknownDomainError,
    clone_database,
    domain_for,
    materialize_world,
)
from agentgauntlet.runner.trajectory import is_complete, read_status, read_steps
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.replay import partial_match
from agentgauntlet.tasks.schema import Task


def _task(task_id: str) -> Task:
    return next(task for task in load_tasks() if task.id == task_id)


def _config(
    root: Path,
    *,
    run_id: str = "demo",
    k: int = 1,
    timeout: float = 30,
) -> RunConfig:
    return RunConfig(run_id=run_id, runs_dir=root, k=k, concurrency=4, timeout_seconds=timeout)


def _probe(fail_times: int, *, retryable: bool) -> MCPServer[None]:
    server: MCPServer[None] = MCPServer("probe", log_level="ERROR")
    seen = {"n": 0}

    @server.tool()
    def probe() -> str:
        """Fail a few times, then return ok."""
        seen["n"] += 1
        if seen["n"] <= fail_times:
            if retryable:
                raise ToolError("timeout: slow. This error is retryable.")
            raise ToolError("cannot_cancel: this order cannot be cancelled.")
        return "ok"

    return server


async def test_scripted_agent_plays_the_reference_in_order() -> None:
    """The scripted agent walks the reference, then returns its final answer."""
    task = _task("retail-012")
    agent = ScriptedAgent()
    history: list[StepRecord] = []
    for call in task.reference_solution.tool_calls:
        action = await agent.act(task, history)
        assert action.tool == call.tool
        assert action.arguments == call.arguments
        history.append(StepRecord(index=len(history), kind="tool", tool=action.tool, text=""))
    finished = await agent.act(task, history)
    assert finished.final_answer == task.reference_solution.final_answer


def test_action_and_run_id_reject_bad_values() -> None:
    """An action is one thing, and a run id is one path segment."""
    with pytest.raises(ValidationError):
        Action(tool="get_order", final_answer="done")
    with pytest.raises(ValidationError):
        Action()
    with pytest.raises(ValidationError):
        RunConfig(run_id="../escape")


def test_clone_matches_the_template_and_unknown_worlds_fail(tmp_path: Path) -> None:
    """A trial copy starts equal to the template. An unknown world is refused."""
    world = materialize_world("retail", tmp_path / "template.sqlite", seed=17)
    clone_database(world.db_path, tmp_path / "copy.sqlite")
    copy = domain_for("retail", tmp_path / "copy.sqlite", seed=17)
    assert copy.snapshot() == world.snapshot()
    with pytest.raises(UnknownDomainError):
        domain_for("space", tmp_path / "space.sqlite", seed=17)


def test_message_text_and_unfinished_files(tmp_path: Path) -> None:
    """Only a text block is kept, and a file without a result line is unfinished."""
    assert message_text(CallToolResult(content=[], is_error=False)) == ""
    image = CallToolResult.model_validate(
        {"content": [{"type": "image", "data": "aa", "mimeType": "image/png"}], "isError": False}
    )
    assert message_text(image) == ""
    text = CallToolResult(content=[TextContent(type="text", text="ok")], is_error=False)
    assert message_text(text) == "ok"
    broken = tmp_path / "trial-00.jsonl"
    broken.write_text("[]\n", encoding="utf-8")
    assert not is_complete(broken)
    broken.write_text("\nnot-json\n", encoding="utf-8")
    assert not is_complete(broken)
    broken.write_text('{"type": "result", "status": "nope", "tool_calls": 0}\n', encoding="utf-8")
    assert read_status(broken) is None
    broken.write_text(
        '\n{"type": "result", "status": "completed", "final_answer": "", "tool_calls": 0}\n',
        encoding="utf-8",
    )
    assert read_status(broken) == "completed"


def test_summary_counts_completed_trials() -> None:
    """Skipped trials still count as completed when that was their result."""
    summary = RunSummary(
        run_id="demo",
        trials=[
            TrialOutcome(
                task_id="retail-001", trial=0, status="completed", skipped=True, path=Path("a")
            ),
            TrialOutcome(
                task_id="retail-001", trial=1, status="timeout", skipped=False, path=Path("b")
            ),
        ],
    )
    assert summary.completed == 1
    assert format_summary(summary) == "run demo: 2 trials, 1 completed, 1 ran, 1 skipped"


def test_session_rejects_negative_retries() -> None:
    """A negative retry count is a caller bug, not a tool failure."""
    with pytest.raises(ValueError, match="retries"):
        ToolSession(client=None, retries=-1)  # type: ignore[arg-type]


async def test_session_retries_only_retryable_errors() -> None:
    """A retryable error is tried again. A business-rule error is not."""
    async with Client(_probe(1, retryable=True)) as client:
        session = ToolSession(client, retries=1)
        recovered = await session.call("probe", {})
        listed = await session.list_tools()
    assert recovered.attempts == 2
    assert recovered.is_error is False
    assert listed == ["probe"]

    async with Client(_probe(5, retryable=True)) as client:
        exhausted = await ToolSession(client, retries=1).call("probe", {})
    assert exhausted.attempts == 2
    assert exhausted.is_error is True
    assert exhausted.retryable is True

    async with Client(_probe(1, retryable=False)) as client:
        refused = await ToolSession(client, retries=4).call("probe", {})
    assert refused.attempts == 1
    assert refused.is_error is True
    assert refused.retryable is False


async def test_trials_do_not_share_a_database(tmp_path: Path) -> None:
    """Both trials can cancel A1045, so the second one did not see the first write."""
    summary = await run_benchmark([_task("retail-005")], ScriptedAgent(), _config(tmp_path, k=2))
    assert [trial.status for trial in summary.trials] == ["completed", "completed"]
    for outcome in summary.trials:
        cancels = [step for step in read_steps(outcome.path) if step.tool == "cancel_order"]
        assert len(cancels) == 1
        assert cancels[0].is_error is False


async def test_resume_skips_finished_trials_and_reruns_partial_ones(tmp_path: Path) -> None:
    """A result line is enough to skip. A header with no result is run again."""
    config = _config(tmp_path, k=2, run_id="resume")
    first = await run_benchmark([_task("retail-001")], ScriptedAgent(), config)
    original = first.trials[0].path.read_bytes()
    first.trials[1].path.write_text('{"type": "trial"}\n', encoding="utf-8")
    second = await run_benchmark([_task("retail-001")], ScriptedAgent(), config)
    assert second.trials[0].skipped is True
    assert second.trials[0].path.read_bytes() == original
    assert second.trials[1].skipped is False
    assert second.trials[1].status == "completed"


async def test_runner_stops_at_the_step_limit_timeout_and_agent_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner records a limit, a timeout, and an exception instead of crashing."""
    limited = _task("retail-005").model_copy(update={"max_steps": 1})
    limit = await run_benchmark([limited], ScriptedAgent(), _config(tmp_path / "limit"))
    assert limit.trials[0].status == "step_limit"
    tools = [step.tool for step in read_steps(limit.trials[0].path) if step.kind == "tool"]
    assert tools == ["get_order"]

    class SlowAgent:
        name = "slow"

        async def act(
            self,
            task: Task,
            history: list[StepRecord],
            tools: Sequence[ToolSpec] | None = None,
        ) -> Action:
            await asyncio.sleep(5)
            return Action(final_answer="late")

    timed = await run_benchmark(
        [_task("retail-001")],
        SlowAgent(),
        _config(tmp_path / "slow", timeout=0.05),
    )
    assert timed.trials[0].status == "timeout"

    class BoomAgent:
        name = "boom"

        async def act(
            self,
            task: Task,
            history: list[StepRecord],
            tools: Sequence[ToolSpec] | None = None,
        ) -> Action:
            raise RuntimeError("disk full")

    blown = await run_benchmark([_task("retail-001")], BoomAgent(), _config(tmp_path / "boom"))
    assert blown.trials[0].status == "error"
    assert "disk full" in blown.trials[0].path.read_text(encoding="utf-8")

    class EmptyAgent:
        name = "empty"

        async def act(
            self,
            task: Task,
            history: list[StepRecord],
            tools: Sequence[ToolSpec] | None = None,
        ) -> Action:
            return Action.model_construct()

    empty = await run_benchmark([_task("retail-001")], EmptyAgent(), _config(tmp_path / "empty"))
    assert empty.trials[0].status == "error"
    assert "neither a tool" in empty.trials[0].path.read_text(encoding="utf-8")

    class OneCallAgent:
        name = "once"

        async def act(
            self,
            task: Task,
            history: list[StepRecord],
            tools: Sequence[ToolSpec] | None = None,
        ) -> Action:
            return Action(tool="get_order", arguments={"order_id": "A1043"})

    async def hang(self: ToolSession, tool: str, arguments: dict[str, object]) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(ToolSession, "call", hang)
    stalled = await run_benchmark(
        [_task("retail-001")],
        OneCallAgent(),
        _config(tmp_path / "stall", timeout=0.05),
    )
    assert stalled.trials[0].status == "timeout"


async def test_unknown_domain_is_a_recorded_error(tmp_path: Path) -> None:
    """A task for a missing world does not abort the run. The trial file explains why."""
    base = _task("retail-001")
    data = base.model_dump()
    data["domain"] = "space"
    data["id"] = "space-001"
    ghost = Task.model_construct(**data)
    summary = await run_benchmark([ghost], ScriptedAgent(), _config(tmp_path))
    assert summary.trials[0].status == "error"
    assert "space" in summary.trials[0].path.read_text(encoding="utf-8")


async def test_scripted_retail_run_reaches_every_expected_state(tmp_path: Path) -> None:
    """Every retail reference, played by the runner, leaves the expected rows."""
    tasks = [task for task in load_tasks() if task.domain == "retail"]
    summary = await run_benchmark(tasks, ScriptedAgent(), _config(tmp_path, run_id="retail"))
    assert summary.completed == 25
    assert len(summary.trials) == 25
    for task, outcome in zip(tasks, summary.trials, strict=True):
        world = domain_for("retail", outcome.path.with_suffix(".sqlite"), seed=task.seed)
        assert partial_match(world.snapshot(), task.expected_state) == []
        called = [step.tool for step in read_steps(outcome.path) if step.kind == "tool"]
        assert called == [call.tool for call in task.reference_solution.tool_calls]


def test_module_command_runs_one_task_and_rejects_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The module command writes a trajectory and a one-line summary."""
    code = main(
        ["--run-id", "smoke", "--k", "1", "--tasks", "retail-001", "--runs-dir", str(tmp_path)]
    )
    assert code == 0
    assert "1 completed" in capsys.readouterr().err
    assert (tmp_path / "smoke" / "retail-001" / "trial-00.jsonl").is_file()

    missing = main(["--run-id", "smoke", "--tasks", "retail-999", "--runs-dir", str(tmp_path)])
    assert missing == 1
    assert "No tasks" in capsys.readouterr().err

    bad = main(["--run-id", "smoke", "--k", "0", "--runs-dir", str(tmp_path)])
    assert bad == 2


def test_module_command_reports_an_unsuccessful_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run whose trials did not finish is a failed command, including a whole domain."""

    async def failed(tasks: list[Task], agent: ScriptedAgent, config: RunConfig) -> RunSummary:
        return RunSummary(
            run_id=config.run_id,
            trials=[
                TrialOutcome(
                    task_id="retail-001",
                    trial=0,
                    status="error",
                    skipped=False,
                    path=tmp_path / "missing.jsonl",
                )
            ],
        )

    monkeypatch.setattr("agentgauntlet.runner.__main__.run_benchmark", failed)
    code = main(["--run-id", "smoke", "--k", "1", "--tasks", "retail", "--runs-dir", str(tmp_path)])
    assert code == 1
    assert "0 completed" in capsys.readouterr().err
