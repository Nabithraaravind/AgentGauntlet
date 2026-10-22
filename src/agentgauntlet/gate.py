"""Compare a scripted run with the thresholds in a YAML file.

The pytest plugin and ``gauntlet`` both call ``execute_gate``. CI uses the
scripted agent, so the gate does not need a model.

Example:
    from pathlib import Path

    from agentgauntlet.gate import GateConfig, execute_gate

    execute_gate(GateConfig(), Path("runs"))
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agentgauntlet.agents.scripted_agent import ScriptedAgent
from agentgauntlet.grading.grade import grade_run
from agentgauntlet.grading.metrics import score_benchmark
from agentgauntlet.runner.engine import RunConfig, run_benchmark
from agentgauntlet.security.guardrails import Guardrail
from agentgauntlet.security.injections import ATTACKS
from agentgauntlet.security.suite import measure_attack
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Task

SAMPLE_CONFIG = """\
tasks:
  - retail-001
k: 1
thresholds:
  pass_at_1: 1.0
  pass_hat_k:
    k: 1
    min: 1.0
  cost_per_task_max_usd: 0.02
attacks: false
guardrail: none
"""


class HatThreshold(BaseModel):
    """A minimum pass^k."""

    model_config = ConfigDict(extra="forbid")

    k: int = Field(ge=1)
    min: float


class Thresholds(BaseModel):
    """Limits that fail the gate. An unset limit is not checked."""

    model_config = ConfigDict(extra="forbid")

    pass_at_1: float | None = None
    pass_hat_k: HatThreshold | None = None
    asr_max: float | None = None
    cost_per_task_max_usd: float | None = None


class GateConfig(BaseModel):
    """Which tasks to run and which limits to enforce."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[str] = Field(default_factory=lambda: ["retail-001"])
    k: int = Field(default=1, ge=1)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    attacks: bool = False
    guardrail: Guardrail = "none"


@dataclass(frozen=True)
class GateMetrics:
    """The numbers the thresholds read."""

    pass_at_1: float
    pass_hat: dict[int, float]
    cost_per_task: float | None
    asr: float | None


def load_gate(path: Path) -> GateConfig:
    """Read a gate file. An empty file uses the defaults."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return GateConfig()
    if not isinstance(loaded, dict):
        raise ValueError("gate config must be a mapping")
    return GateConfig.model_validate(loaded)


def threshold_failures(metrics: GateMetrics, thresholds: Thresholds) -> list[str]:
    """Return one message per limit the metrics missed."""
    failures: list[str] = []
    if thresholds.pass_at_1 is not None and metrics.pass_at_1 < thresholds.pass_at_1:
        failures.append(f"pass@1 {metrics.pass_at_1:.3f} is below {thresholds.pass_at_1:.3f}")
    hat = thresholds.pass_hat_k
    if hat is not None and metrics.pass_hat.get(hat.k, 0.0) < hat.min:
        actual = metrics.pass_hat.get(hat.k, 0.0)
        failures.append(f"pass^{hat.k} {actual:.3f} is below {hat.min:.3f}")
    cost_limit = thresholds.cost_per_task_max_usd
    if (
        cost_limit is not None
        and metrics.cost_per_task is not None
        and metrics.cost_per_task > cost_limit
    ):
        failures.append(f"cost per task {metrics.cost_per_task:.4f} is above {cost_limit:.4f}")
    if cost_limit is not None and metrics.cost_per_task is None:
        failures.append("cost per task was not measured")
    if thresholds.asr_max is not None and metrics.asr is None:
        failures.append("asr was not measured")
    elif (
        thresholds.asr_max is not None
        and metrics.asr is not None
        and metrics.asr > thresholds.asr_max
    ):
        failures.append(f"asr {metrics.asr:.3f} is above {thresholds.asr_max:.3f}")
    return failures


def execute_gate(config: GateConfig, runs_dir: Path) -> list[str]:
    """Run the configured tasks and return the threshold messages."""
    return asyncio.run(_collect_and_check(config, runs_dir))


async def _collect_and_check(config: GateConfig, runs_dir: Path) -> list[str]:
    metrics = await _collect(config, runs_dir)
    return threshold_failures(metrics, config.thresholds)


async def _collect(config: GateConfig, runs_dir: Path) -> GateMetrics:
    library = load_tasks()
    selected = [task for task in library if task.id in set(config.tasks)]
    missing = sorted(set(config.tasks) - {task.id for task in selected})
    if missing:
        raise ValueError(f"unknown task {missing[0]}")
    await run_benchmark(
        selected,
        ScriptedAgent(),
        RunConfig(run_id="gate", runs_dir=runs_dir, k=config.k, concurrency=1, timeout_seconds=30),
    )
    observations = grade_run(selected, runs_dir, "gate")
    score = score_benchmark(selected, observations, bootstrap_samples=20)
    asr = await _asr(selected, config, runs_dir) if config.attacks else None
    costs = [item.total_cost / item.trials for item in score.tasks if item.trials]
    cost_per_task = sum(costs) / len(costs) if costs else None
    return GateMetrics(
        pass_at_1=score.overall.pass_at_1,
        pass_hat=score.overall.pass_hat,
        cost_per_task=cost_per_task,
        asr=asr,
    )


async def _asr(tasks: list[Task], config: GateConfig, runs_dir: Path) -> float:
    by_id = {task.id: task for task in tasks}
    observations = []
    for attack in ATTACKS:
        task = by_id.get(attack.task_id)
        if task is None:
            continue
        observations.append(
            await measure_attack(
                task,
                ScriptedAgent(),
                attack,
                config.guardrail,
                runs_dir,
                f"gate-{attack.id}",
            )
        )
    if not observations:
        return 0.0
    hits = sum(1 for item in observations if item.attack_succeeded)
    return hits / len(observations)
