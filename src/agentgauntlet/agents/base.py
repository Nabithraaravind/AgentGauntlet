"""Agent protocol: look at the task and the steps so far, then act.

Example:
    from agentgauntlet.agents import ScriptedAgent
    from agentgauntlet.tasks import load_tasks

    agent = ScriptedAgent()
    action = await agent.act(load_tasks()[0], [])
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentgauntlet.tasks.schema import JsonScalar, Task


class StepRecord(BaseModel):
    """One line of a trajectory, either a chat message or a tool call.

    ``tokens`` and ``cost_usd`` stay null for the scripted agent. A model agent
    fills them in later.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["step"] = "step"
    index: int = Field(ge=0)
    kind: Literal["tool", "message"]
    role: Literal["user", "assistant", "tool"] | None = None
    tool: str | None = None
    arguments: dict[str, JsonScalar] | None = None
    is_error: bool | None = None
    expect_error: str | None = None
    text: str = ""
    latency_ms: float | None = None
    attempts: int | None = None
    tokens: int | None = None
    cost_usd: float | None = None


class Action(BaseModel):
    """The next thing an agent wants to do.

    A tool call sets ``tool``. A finished agent sets ``final_answer`` and leaves
    ``tool`` empty. ``expect_error`` is only for the scripted agent, which
    already knows a call should fail.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str | None = None
    arguments: dict[str, JsonScalar] = Field(default_factory=dict)
    expect_error: str | None = None
    final_answer: str | None = None

    @model_validator(mode="after")
    def one_outcome(self) -> Action:
        """Reject an action that is both a tool call and a final answer."""
        has_tool = self.tool is not None
        has_answer = self.final_answer is not None
        if has_tool == has_answer:
            raise ValueError("an action is either a tool call or a final answer")
        return self


class Agent(Protocol):
    """Something that can work a task one action at a time."""

    name: str

    async def act(self, task: Task, history: list[StepRecord]) -> Action:
        """Choose the next tool call, or the final answer."""
