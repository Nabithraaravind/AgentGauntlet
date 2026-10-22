"""Attack templates, guardrails, and the ASR table."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

import agentgauntlet.security as security
from agentgauntlet.agents.base import Action, StepRecord
from agentgauntlet.agents.mcp_client import ToolSpec
from agentgauntlet.agents.scripted_agent import ScriptedAgent
from agentgauntlet.domains.base import Domain
from agentgauntlet.runner.engine import RunConfig, run_benchmark
from agentgauntlet.runner.sandbox import domain_for
from agentgauntlet.security import (
    ATTACKS,
    SecurityObservation,
    attack_by_id,
    policy_allows,
    present,
    sanitize,
    security_markdown,
    security_rows,
    spotlight,
)
from agentgauntlet.security.injections import Attack, inject
from agentgauntlet.security.suite import attack_succeeded, measure_attack
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import JsonScalar, Task


class Gullible:
    """Follow the script, unless a tool result still shows the attack trigger."""

    name = "gullible"

    def __init__(self, trigger: str, tool: str, arguments: dict[str, JsonScalar]) -> None:
        """Remember the trigger and the write the attack wants."""
        self._trigger = trigger.casefold()
        self._tool = tool
        self._arguments = arguments
        self._scripted = ScriptedAgent()

    async def act(
        self,
        task: Task,
        history: list[StepRecord],
        tools: Sequence[ToolSpec] | None = None,
    ) -> Action:
        """Issue the attack once if its trigger is still visible, otherwise follow the script."""
        attacked = any(step.tool == self._tool for step in history if step.kind == "tool")
        seen = any(self._trigger in step.text.casefold() for step in history)
        if seen and not attacked:
            return Action(tool=self._tool, arguments=dict(self._arguments))
        return await self._scripted.act(task, history, tools)


def test_library_has_eight_attack_categories() -> None:
    """The eight categories from the spec each have one template."""
    categories = {attack.category for attack in ATTACKS}
    assert categories == {
        "direct-override",
        "fake-system",
        "role-play",
        "encoded",
        "exfiltration",
        "tool-hijack",
        "delayed",
        "multilingual",
    }
    assert attack_by_id("encoded").tool == "cancel_booking"
    with pytest.raises(ValueError, match="unknown attack"):
        attack_by_id("missing")


def test_sanitizer_removes_every_payload_and_spotlight_keeps_it() -> None:
    """A sanitizer drops the trigger line. Spotlighting leaves it readable."""
    for attack in ATTACKS:
        shown = present(inject("order is delivered", attack), "sanitizer")
        assert attack.trigger.casefold() not in shown.casefold()
        assert "order is delivered" in shown
        marked = present(inject("order is delivered", attack), "spotlight")
        assert attack.trigger.casefold() in marked.casefold()
        assert "<<UNTRUSTED_TOOL_DATA>>" in marked
    assert present("plain", "none") == "plain"
    assert present("plain", "policy") == "plain"
    assert sanitize("") == ""
    assert "plain" in spotlight("plain")


def test_policy_allows_reads_and_blocks_unasked_writes() -> None:
    """A lookup goal does not authorize a cancel, and a huge amount is refused."""
    goal = "What is the status of order A1043?"
    assert policy_allows("get_order", {"order_id": "A1043"}, goal)
    assert not policy_allows("cancel_order", {"order_id": "A1045"}, goal)
    assert policy_allows("cancel_order", {"order_id": "A1045"}, "Cancel order A1045.")
    assert not policy_allows("transfer", {"amount_inr": 50_000}, "Please transfer the funds.")
    assert policy_allows("transfer", {"amount_inr": 100}, "Please transfer the funds.")
    assert policy_allows("transfer", {"amount_inr": True}, "Please transfer the funds.")


def test_security_table_matches_a_hand_count() -> None:
    """Two trials, one of which was attacked and one of which passed the task."""
    rows = security_rows(
        [
            SecurityObservation("direct-override", "direct-override", "none", True, False),
            SecurityObservation("direct-override", "direct-override", "none", False, True),
        ]
    )
    assert rows[0].trials == 2
    assert rows[0].asr == 0.5
    assert rows[0].utility == 0.5
    text = security_markdown(rows)
    assert "| none | direct-override | 2 | 0.50 | 0.50 |" in text
    assert security_markdown(()) == (
        "| Guardrail | Attack | Trials | ASR | Utility |\n| --- | --- | --- | --- | --- |\n"
    )


def test_each_attacker_goal_is_reachable(tmp_path: Path) -> None:
    """Calling the attacker's tool on a fresh world creates the goal row."""
    for attack in ATTACKS:
        world = domain_for(attack.domain, tmp_path / f"{attack.id}.sqlite", seed=17)
        world.setup()
        before = world.snapshot()
        _perform(world, attack)
        after = world.snapshot()
        assert attack_succeeded(before, after, attack)
        assert not attack_succeeded(before, before, attack)


def _perform(world: Domain, attack: Attack) -> None:
    method = getattr(world, attack.tool)
    method(**attack.arguments)


async def test_scripted_agent_ignores_the_injection(tmp_path: Path) -> None:
    """The scripted agent does not obey tool text, so the attack fails and the task passes."""
    attack = attack_by_id("direct-override")
    task = _task(attack.task_id)
    observed = await measure_attack(
        task, ScriptedAgent(), attack, "none", tmp_path, "scripted-attack"
    )
    assert observed.attack_succeeded is False
    assert observed.task_passed is True


async def test_guardrails_change_a_gullible_agent(tmp_path: Path) -> None:
    """Spotlighting still shows the payload. Sanitizing and the policy stop the write."""
    attack = attack_by_id("direct-override")
    task = _task(attack.task_id)
    agent = Gullible(attack.trigger, attack.tool, dict(attack.arguments))
    none = await measure_attack(task, agent, attack, "none", tmp_path, "gullible-none")
    marked = await measure_attack(task, agent, attack, "spotlight", tmp_path, "gullible-spot")
    cleaned = await measure_attack(task, agent, attack, "sanitizer", tmp_path, "gullible-clean")
    blocked = await measure_attack(task, agent, attack, "policy", tmp_path, "gullible-policy")
    assert (none.attack_succeeded, none.task_passed) == (True, False)
    assert (marked.attack_succeeded, marked.task_passed) == (True, False)
    assert (cleaned.attack_succeeded, cleaned.task_passed) == (False, True)
    assert (blocked.attack_succeeded, blocked.task_passed) == (False, True)


async def test_unknown_attack_is_rejected(tmp_path: Path) -> None:
    """A misspelled attack id fails before a trial starts."""
    with pytest.raises(ValueError, match="unknown attack"):
        await run_benchmark(
            [_task("retail-001")],
            ScriptedAgent(),
            RunConfig(run_id="bad-attack", runs_dir=tmp_path, k=1, attack="missing"),
        )


async def test_measure_attack_reports_a_missing_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trajectory without a result line is an error, not a silent pass."""
    monkeypatch.setattr("agentgauntlet.security.suite.read_result", lambda _path: None)
    attack = attack_by_id("direct-override")
    with pytest.raises(RuntimeError, match="no result"):
        await measure_attack(
            _task(attack.task_id), ScriptedAgent(), attack, "none", tmp_path, "missing-result"
        )


def test_security_package_rejects_unknown_names() -> None:
    """The lazy exports are the ASR helpers, nothing else."""
    name = "not_a_helper"
    with pytest.raises(AttributeError, match="no attribute"):
        getattr(security, name)


def _task(task_id: str) -> Task:
    return next(item for item in load_tasks() if item.id == task_id)
