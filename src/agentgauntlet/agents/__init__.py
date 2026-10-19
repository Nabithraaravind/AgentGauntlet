"""Agents that can work a task. The scripted agent is the one CI runs.

Example:
    from agentgauntlet.agents import ScriptedAgent

    agent = ScriptedAgent()
"""

from agentgauntlet.agents.base import Action, Agent, StepRecord
from agentgauntlet.agents.scripted_agent import ScriptedAgent

__all__ = ["Action", "Agent", "ScriptedAgent", "StepRecord"]
