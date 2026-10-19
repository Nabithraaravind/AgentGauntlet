"""Deterministic agent that plays a task's reference solution.

Tests and CI use this so a run never needs a model. It does not read tool
results. The next call is always the next line of the script.

Example:
    from agentgauntlet.agents import ScriptedAgent
    from agentgauntlet.tasks import load_tasks

    agent = ScriptedAgent()
    task = next(item for item in load_tasks() if item.id == "retail-001")
    action = await agent.act(task, [])
"""

from __future__ import annotations

from agentgauntlet.agents.base import Action, StepRecord
from agentgauntlet.tasks.schema import Task


class ScriptedAgent:
    """Play ``task.reference_solution`` in order, then return its final answer."""

    name = "scripted"

    async def act(self, task: Task, history: list[StepRecord]) -> Action:
        """Return the next scripted call, or the scripted final answer."""
        finished = sum(1 for step in history if step.kind == "tool")
        calls = task.reference_solution.tool_calls
        if finished < len(calls):
            call = calls[finished]
            return Action(
                tool=call.tool,
                arguments=dict(call.arguments),
                expect_error=call.expect_error,
            )
        return Action(final_answer=task.reference_solution.final_answer)
