"""Grade a finished run and write ``results/<slug>.json``.

Usage:
    uv run python tasks/record_run.py runs/qwen-retail-k3 ollama/qwen2.5:7b-instruct
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from agentgauntlet.grading.grade import grade_run
from agentgauntlet.grading.metrics import score_benchmark
from agentgauntlet.tasks import load_tasks


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-").lower()


def main(argv: list[str]) -> int:
    """Write one results file from a finished run directory."""
    if len(argv) != 3:
        sys.stderr.write("usage: record_run.py RUN_DIR MODEL\n")
        return 2
    run_dir = Path(argv[1])
    model = argv[2]
    observations = grade_run(load_tasks(), run_dir.parent, run_dir.name)
    if not observations:
        sys.stderr.write(f"{run_dir} has no finished trials\n")
        return 1
    used = {item.task_id for item in observations}
    tasks = [task for task in load_tasks() if task.id in used]
    score = score_benchmark(tasks, observations, bootstrap_samples=200)
    payload = {
        "model": model,
        "pass_at_1": score.overall.pass_at_1,
        "pass_hat_5": score.overall.pass_hat.get(5, 0.0),
        "asr": None,
        "cost_per_success": score.overall.cost_per_success,
        "pass_hat": score.overall.pass_hat,
        "interval": list(score.pass_at_1_interval),
        "failures": score.overall.failures,
        "run_id": run_dir.name,
        "tasks": len(tasks),
        "trials": len(observations),
    }
    dest = Path("results") / f"{_slug(model)}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {dest}\n{json.dumps(payload, indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
