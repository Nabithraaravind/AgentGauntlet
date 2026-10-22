"""ReAct agent: one LiteLLM call, then either a tool or a final answer.

The runner still executes the tool. This class only decides the next action
and prices that decision. Tests pass a ``complete`` function so they never
call a model.

Example:
    from agentgauntlet.agents import ReactAgent

    agent = ReactAgent("ollama/qwen2.5:7b-instruct", temperature=0)
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agentgauntlet.agents.base import Action, StepRecord
from agentgauntlet.agents.mcp_client import ToolSpec
from agentgauntlet.cost.tracker import usage_cost_usd
from agentgauntlet.runner.sandbox import domain_for
from agentgauntlet.tasks.schema import JsonScalar, Task

Message = dict[str, object]
Completer = Callable[[list[Message], Sequence[ToolSpec]], "ModelTurn"]


@dataclass(frozen=True)
class ModelTurn:
    """The text or tool call from one model response, plus its token counts."""

    text: str
    tool_name: str | None
    arguments: dict[str, JsonScalar]
    prompt_tokens: int
    completion_tokens: int


class ReactAgent:
    """Ask LiteLLM what to do next, with the retail policy in the system prompt."""

    def __init__(
        self,
        model: str = "ollama/qwen2.5:7b-instruct",
        *,
        temperature: float = 0,
        api_base: str | None = None,
        gpu_usd_per_hour: float = 0,
        complete: Completer | None = None,
    ) -> None:
        """Bind a model. ``complete`` replaces LiteLLM in tests."""
        self.model = model
        self.name = f"react:{model}"
        self.temperature = temperature
        self.api_base = api_base
        self.gpu_usd_per_hour = gpu_usd_per_hour
        self._complete = complete or self._default_complete

    async def act(
        self,
        task: Task,
        history: list[StepRecord],
        tools: Sequence[ToolSpec] | None = None,
    ) -> Action:
        """Make one model call and return its tool call or final answer."""
        specs = list(tools or [])
        messages = transcript(task, _policy(task), history)
        started = time.perf_counter()
        turn = await asyncio.to_thread(self._complete, messages, specs)
        latency_ms = (time.perf_counter() - started) * 1000
        cost = usage_cost_usd(
            self.model,
            turn.prompt_tokens,
            turn.completion_tokens,
            latency_ms=latency_ms,
            gpu_usd_per_hour=self.gpu_usd_per_hour,
        )
        if turn.tool_name is not None:
            return Action(
                tool=turn.tool_name,
                arguments=turn.arguments,
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
            )
        return Action(
            final_answer=turn.text,
            prompt_tokens=turn.prompt_tokens,
            completion_tokens=turn.completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )

    def _default_complete(self, messages: list[Message], tools: Sequence[ToolSpec]) -> ModelTurn:
        return litellm_complete(
            self.model,
            messages,
            tools,
            temperature=self.temperature,
            api_base=self.api_base,
        )


def transcript(task: Task, policy: str, history: list[StepRecord]) -> list[Message]:
    """Build the chat the model sees: policy, then each recorded step."""
    system = (
        "You are a tool-using support agent. Follow the policy. "
        "Call one tool when you need the database. "
        "When the task is finished, reply to the customer and do not call a tool.\n\n"
        f"{policy}"
    )
    messages: list[Message] = [{"role": "system", "content": system}]
    for step in history:
        if step.kind == "message" and step.role in {"user", "assistant"}:
            messages.append({"role": step.role, "content": step.text})
        elif step.kind == "tool" and step.tool is not None:
            call_id = f"call-{step.index}"
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": step.tool,
                                "arguments": json.dumps(step.arguments or {}, ensure_ascii=False),
                            },
                        }
                    ],
                }
            )
            messages.append({"role": "tool", "tool_call_id": call_id, "content": step.text})
    return messages


def litellm_complete(
    model: str,
    messages: list[Message],
    tools: Sequence[ToolSpec],
    *,
    temperature: float,
    api_base: str | None,
) -> ModelTurn:
    """Call LiteLLM once and read the first tool call, or the text reply."""
    import litellm

    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = [_openai_tool(spec) for spec in tools]
        kwargs["tool_choice"] = "auto"
    if api_base:
        kwargs["api_base"] = api_base
    raw: object = litellm.completion(**kwargs)
    return _parse_completion(raw)


def _policy(task: Task) -> str:
    return domain_for(task.domain, Path("unused.sqlite"), seed=task.seed).policy()


def _openai_tool(spec: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _parse_completion(raw: object) -> ModelTurn:
    choices = getattr(raw, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise ValueError("model response had no choices")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    text = content if isinstance(content, str) else ""
    tool_name, arguments = _first_tool(getattr(message, "tool_calls", None))
    usage = getattr(raw, "usage", None)
    return ModelTurn(
        text=text,
        tool_name=tool_name,
        arguments=arguments,
        prompt_tokens=_count(getattr(usage, "prompt_tokens", 0)),
        completion_tokens=_count(getattr(usage, "completion_tokens", 0)),
    )


def _first_tool(tool_calls: object) -> tuple[str | None, dict[str, JsonScalar]]:
    if not isinstance(tool_calls, list) or not tool_calls:
        return None, {}
    function = getattr(tool_calls[0], "function", None)
    name = getattr(function, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError("model tool call had no name")
    return name, _arguments(getattr(function, "arguments", "{}"))


def _arguments(raw: object) -> dict[str, JsonScalar]:
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str):
        loaded: object = json.loads(raw) if raw else {}
        if not isinstance(loaded, dict):
            raise ValueError("tool arguments must be a JSON object")
        payload = loaded
    else:
        raise ValueError("tool arguments must be a JSON object")
    arguments: dict[str, JsonScalar] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ValueError("tool argument names must be strings")
        arguments[key] = _scalar(key, value)
    return arguments


def _scalar(key: str, value: object) -> JsonScalar:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    raise ValueError(f"tool argument {key} is not a scalar")


def _count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0
