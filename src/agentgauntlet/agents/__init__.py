"""Agents that can work a task. CI runs the scripted agent, not the model.

Example:
    from agentgauntlet.agents import ReactAgent, ScriptedAgent

    scripted = ScriptedAgent()
    local = ReactAgent("ollama/qwen2.5:7b-instruct")
"""

from agentgauntlet.agents.base import Action, Agent, StepRecord
from agentgauntlet.agents.react_agent import ReactAgent
from agentgauntlet.agents.scripted_agent import ScriptedAgent

__all__ = ["Action", "Agent", "ReactAgent", "ScriptedAgent", "StepRecord"]
