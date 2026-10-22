"""The ReAct agent decides one action per call. These tests never call a model."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from mcp import Client

from agentgauntlet.agents import Action, ReactAgent, StepRecord
from agentgauntlet.agents.mcp_client import ToolSession, ToolSpec
from agentgauntlet.agents.react_agent import (
    ModelTurn,
    _arguments,
    litellm_complete,
    transcript,
)
from agentgauntlet.domains.retail import RetailDomain
from agentgauntlet.runner import RunConfig, RunSummary, TrialOutcome, run_benchmark
from agentgauntlet.runner.__main__ import _agent, main
from agentgauntlet.runner.trajectory import read_steps
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Task


def _task() -> Task:
    return next(task for task in load_tasks() if task.id == "retail-001")


def _tool_step() -> StepRecord:
    return StepRecord(
        index=1,
        kind="tool",
        role="tool",
        tool="get_order",
        arguments={"order_id": "A1043"},
        text="ok",
    )


def test_transcript_carries_the_policy_and_the_tool_result() -> None:
    """The model sees the SOP and the last tool text, so it can recover from an error."""
    task = _task()
    history = [
        StepRecord(index=0, kind="message", role="user", text=task.user_goal),
        StepRecord(index=2, kind="message", role="tool", text="ignored"),
        StepRecord(index=3, kind="tool", role="tool", tool=None, text="ignored"),
        _tool_step(),
    ]
    messages = transcript(task, "Return within 30 days.", history)
    assert messages[0]["role"] == "system"
    assert "30 days" in str(messages[0]["content"])
    assert messages[1] == {"role": "user", "content": task.user_goal}
    tool_calls = messages[2]["tool_calls"]
    assert isinstance(tool_calls, list)
    first = tool_calls[0]
    assert isinstance(first, dict)
    function = first["function"]
    assert isinstance(function, dict)
    assert function["name"] == "get_order"
    assert messages[3]["content"] == "ok"


def test_arguments_keep_scalars_and_whole_number_floats() -> None:
    """2499.0 becomes 2499. A nested object is rejected."""
    assert _arguments(
        '{"order_id": "A1043", "amount": 2499.0, "rate": 1.5, "ok": true, "qty": 2}'
    ) == {
        "order_id": "A1043",
        "amount": 2499,
        "rate": 1.5,
        "ok": True,
        "qty": 2,
    }
    assert _arguments({"flag": False, "note": None}) == {"flag": False, "note": None}
    assert _arguments("") == {}
    with pytest.raises(ValueError, match="JSON object"):
        _arguments("[1]")
    with pytest.raises(ValueError, match="JSON object"):
        _arguments(1)
    with pytest.raises(ValueError, match="names"):
        _arguments({1: "x"})
    with pytest.raises(ValueError, match="not a scalar"):
        _arguments({"row": {"id": "A1"}})


async def test_act_returns_a_priced_tool_call_or_a_final_answer() -> None:
    """A fake completer stands in for LiteLLM and records the messages it was given."""
    seen: list[list[dict[str, object]]] = []

    def complete(messages: list[dict[str, object]], tools: Sequence[ToolSpec]) -> ModelTurn:
        seen.append(messages)
        assert [tool.name for tool in tools] == ["get_order"]
        if len(seen) == 1:
            return ModelTurn("", "get_order", {"order_id": "A1043"}, 11, 7)
        return ModelTurn("Order A1043 is delivered.", None, {}, 0, 4)

    agent = ReactAgent("ollama/qwen2.5:7b-instruct", gpu_usd_per_hour=0, complete=complete)
    specs = [ToolSpec("get_order", "Read an order", {"type": "object"})]
    first = await agent.act(_task(), [], specs)
    assert first.tool == "get_order"
    assert first.arguments == {"order_id": "A1043"}
    assert first.prompt_tokens == 11
    assert first.completion_tokens == 7
    assert first.cost_usd == 0
    assert agent.name == "react:ollama/qwen2.5:7b-instruct"
    second = await agent.act(_task(), [_tool_step()], specs)
    assert second.final_answer == "Order A1043 is delivered."
    assert second.prompt_tokens == 0
    assert "30 days" in str(seen[0][0]["content"])


def test_default_complete_delegates_to_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production path is the LiteLLM wrapper, with the agent's temperature."""

    def fake(
        model: str,
        messages: list[dict[str, object]],
        tools: Sequence[ToolSpec],
        *,
        temperature: float,
        api_base: str | None,
    ) -> ModelTurn:
        assert model == "ollama/qwen2.5:7b-instruct"
        assert messages == []
        assert list(tools) == []
        assert temperature == 0
        assert api_base is None
        return ModelTurn("done", None, {}, 1, 1)

    monkeypatch.setattr("agentgauntlet.agents.react_agent.litellm_complete", fake)
    turn = ReactAgent()._default_complete([], [])
    assert turn.text == "done"


def test_litellm_complete_reads_a_tool_call_and_a_text_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper reads the first tool call and ignores a missing usage block."""
    import litellm

    captured: list[dict[str, object]] = []

    def completion(**kwargs: object) -> object:
        captured.append(kwargs)
        if kwargs.get("tools"):
            return _response(
                content=None,
                arguments='{"order_id": "A1043"}',
                prompt_tokens=True,
            )
        return _response(content="done", arguments=None, prompt_tokens=3)

    monkeypatch.setattr(litellm, "completion", completion)
    spec = ToolSpec("get_order", "Read an order", {"type": "object"})
    tool_turn = litellm_complete(
        "ollama/qwen2.5:7b-instruct",
        [{"role": "user", "content": "hi"}],
        [spec],
        temperature=0,
        api_base="http://localhost:11434",
    )
    assert tool_turn.tool_name == "get_order"
    assert tool_turn.arguments == {"order_id": "A1043"}
    assert tool_turn.prompt_tokens == 0
    text_turn = litellm_complete(
        "ollama/qwen2.5:7b-instruct",
        [],
        [],
        temperature=0,
        api_base=None,
    )
    assert text_turn.tool_name is None
    assert text_turn.text == "done"
    assert text_turn.prompt_tokens == 3
    assert "api_base" not in captured[1]
    assert captured[0]["api_base"] == "http://localhost:11434"


def test_litellm_complete_rejects_an_empty_or_nameless_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response with no choices, or a tool call with no name, is an error."""
    import litellm

    def empty(**_kwargs: object) -> object:
        return _response(content="x", arguments=None, choices=[])

    monkeypatch.setattr(litellm, "completion", empty)
    with pytest.raises(ValueError, match="no choices"):
        litellm_complete("ollama/x", [], [], temperature=0, api_base=None)

    def nameless(**_kwargs: object) -> object:
        return _response(content=None, arguments="{}", name="")

    monkeypatch.setattr(litellm, "completion", nameless)
    with pytest.raises(ValueError, match="no name"):
        litellm_complete(
            "ollama/x",
            [],
            [ToolSpec("get_order", "", {})],
            temperature=0,
            api_base=None,
        )

    def unnamed(**_kwargs: object) -> object:
        return _response(content=None, arguments="{}", name=None)

    monkeypatch.setattr(litellm, "completion", unnamed)
    with pytest.raises(ValueError, match="no name"):
        litellm_complete(
            "ollama/x",
            [],
            [ToolSpec("get_order", "", {})],
            temperature=0,
            api_base=None,
        )


async def test_runner_stores_model_cost_on_the_trajectory(tmp_path: Path) -> None:
    """Tokens from the action land on the tool step and on the final answer."""

    class PricedAgent:
        name = "priced"
        model = "priced-model"

        async def act(
            self,
            task: Task,
            history: list[StepRecord],
            tools: Sequence[ToolSpec] | None = None,
        ) -> Action:
            if not any(step.kind == "tool" for step in history):
                return Action(
                    tool="get_order",
                    arguments={"order_id": "A1043"},
                    prompt_tokens=10,
                    completion_tokens=0,
                    cost_usd=0.5,
                    latency_ms=8,
                )
            return Action(
                final_answer="Order A1043 is delivered.",
                prompt_tokens=0,
                completion_tokens=4,
                cost_usd=0.25,
                latency_ms=0,
            )

    summary = await run_benchmark(
        [_task()],
        PricedAgent(),
        RunConfig(run_id="priced", runs_dir=tmp_path, k=1, concurrency=1, timeout_seconds=30),
    )
    steps = read_steps(summary.trials[0].path)
    tool = next(step for step in steps if step.kind == "tool")
    answer = next(step for step in steps if step.role == "assistant")
    assert tool.tokens == 10
    assert tool.cost_usd == 0.5
    assert tool.latency_ms is not None
    assert tool.latency_ms >= 8
    assert answer.tokens == 4
    assert answer.cost_usd == 0.25
    assert answer.latency_ms == 0
    manifest = json.loads((tmp_path / "priced" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model"] == "priced-model"


async def test_tool_specs_keep_the_schema_and_default_a_missing_one(tmp_path: Path) -> None:
    """A retail tool keeps its JSON schema. A tool with no schema gets an empty object."""
    world = RetailDomain(tmp_path / "world.sqlite", seed=17)
    world.setup()
    async with Client(world.mcp_server()) as client:
        specs = await ToolSession(client).list_tool_specs()
    order = next(spec for spec in specs if spec.name == "get_order")
    properties = order.parameters["properties"]
    assert isinstance(properties, dict)
    assert "order_id" in properties

    class BareTool:
        name = "noop"
        description = None
        input_schema = None

    class Listed:
        def __init__(self) -> None:
            self.tools = [BareTool()]

    class BareClient:
        async def list_tools(self) -> Listed:
            return Listed()

    bare = await ToolSession(BareClient(), retries=0).list_tool_specs()  # type: ignore[arg-type]
    assert bare == [ToolSpec("noop", "", {})]


def test_react_command_builds_a_react_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--agent react`` does not call the model when the run itself is replaced."""
    seen: list[ReactAgent] = []

    async def capture(tasks: list[Task], agent: ReactAgent, config: RunConfig) -> RunSummary:
        seen.append(agent)
        return RunSummary(
            run_id=config.run_id,
            trials=[
                TrialOutcome(
                    task_id=tasks[0].id,
                    trial=0,
                    status="completed",
                    skipped=False,
                    path=tmp_path / "missing.jsonl",
                )
            ],
        )

    monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")
    monkeypatch.setattr("agentgauntlet.runner.__main__.run_benchmark", capture)
    code = main(
        [
            "--agent",
            "react",
            "--model",
            "ollama/qwen2.5:7b-instruct",
            "--gpu-usd-per-hour",
            "2",
            "--run-id",
            "qwen",
            "--k",
            "1",
            "--tasks",
            "retail-001",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert seen[0].model == "ollama/qwen2.5:7b-instruct"
    assert seen[0].api_base == "http://127.0.0.1:11434"
    assert seen[0].gpu_usd_per_hour == 2
    assert "1 completed" in capsys.readouterr().err
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    plain = _agent(argparse.Namespace(agent="react", model="ollama/x", gpu_usd_per_hour=0))
    assert isinstance(plain, ReactAgent)
    assert plain.api_base is None


def _response(
    *,
    content: str | None,
    arguments: str | None,
    prompt_tokens: int | bool = 3,
    name: object = "get_order",
    choices: list[object] | None = None,
) -> object:
    class Function:
        def __init__(self) -> None:
            self.name = name
            self.arguments = arguments

    class Call:
        function = Function()

    class Message:
        def __init__(self) -> None:
            self.content = content
            self.tool_calls = None if arguments is None else [Call()]

    class Choice:
        message = Message()

    class Usage:
        def __init__(self) -> None:
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = 2

    class Response:
        def __init__(self) -> None:
            self.choices = [Choice()] if choices is None else choices
            self.usage = Usage()

    return Response()
