"""Read and write one trial as a JSONL file.

A trial is finished when the last line is a result. Resume skips those files.
A crash before the result line leaves the trial unfinished, so the next run
does it again.

Example:
    from agentgauntlet.runner.trajectory import is_complete, trial_path

    path = trial_path(runs, "demo", "retail-001", 0)
    done = is_complete(path)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentgauntlet.agents.base import StepRecord

TrialStatus = Literal["completed", "timeout", "step_limit", "error"]


class TrialHeader(BaseModel):
    """The first line of a trajectory."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["trial"] = "trial"
    run_id: str
    task_id: str
    trial: int = Field(ge=0)
    seed: int
    agent: str
    domain: str
    tools: list[str]


class TrialResult(BaseModel):
    """The last line of a finished trajectory.

    ``completed`` means the agent returned a final answer. It does not mean the
    database matched. That check is grading.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["result"] = "result"
    status: TrialStatus
    final_answer: str = ""
    tool_calls: int = Field(ge=0)
    error: str | None = None


def trial_path(runs_dir: Path, run_id: str, task_id: str, trial: int) -> Path:
    """Return the JSONL path for one ``(task, trial)`` pair."""
    return runs_dir / run_id / task_id / f"trial-{trial:02d}.jsonl"


def database_path(runs_dir: Path, run_id: str, task_id: str, trial: int) -> Path:
    """Return the SQLite path that sits beside a trajectory."""
    return runs_dir / run_id / task_id / f"trial-{trial:02d}.sqlite"


def template_path(runs_dir: Path, run_id: str, task_id: str) -> Path:
    """Return the seed database copied for every trial of a task."""
    return runs_dir / run_id / "_templates" / f"{task_id}.sqlite"


def is_complete(path: Path) -> bool:
    """Return whether ``path`` ends with a result line."""
    return read_status(path) is not None


def read_status(path: Path) -> TrialStatus | None:
    """Return the result status, or ``None`` when the trial is unfinished."""
    result = read_result(path)
    if result is None:
        return None
    return result.status


def read_result(path: Path) -> TrialResult | None:
    """Return the result line, or ``None`` when the trial is unfinished."""
    return _last_result(path)


def write_trajectory(
    path: Path,
    header: TrialHeader,
    steps: list[StepRecord],
    result: TrialResult,
) -> None:
    """Write the trajectory atomically so a crash cannot look finished."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header, *steps, result]
    payload = "".join(_dump(line) + "\n" for line in lines)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def read_steps(path: Path) -> list[StepRecord]:
    """Return the step lines from a trajectory."""
    steps: list[StepRecord] = []
    for record in _records(path):
        if record.get("type") == "step":
            steps.append(StepRecord.model_validate(record))
    return steps


def _last_result(path: Path) -> TrialResult | None:
    records = _records(path)
    if not records or records[-1].get("type") != "result":
        return None
    try:
        return TrialResult.model_validate(records[-1])
    except ValidationError:
        return None


def _records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded: object = json.loads(line)
        except json.JSONDecodeError:
            return []
        if not isinstance(loaded, dict):
            return []
        records.append(cast(dict[str, object], loaded))
    return records


def _dump(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)
