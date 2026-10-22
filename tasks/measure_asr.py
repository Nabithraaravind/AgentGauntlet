"""Run the injection suite for one model and print the ASR table.

Usage:
    uv run python tasks/measure_asr.py ollama/qwen2.5:7b-instruct
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from agentgauntlet.agents.react_agent import ReactAgent
from agentgauntlet.security.guardrails import Guardrail
from agentgauntlet.security.injections import ATTACKS
from agentgauntlet.security.suite import measure_attack, security_markdown, security_rows
from agentgauntlet.tasks import load_tasks


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-").lower()


async def _run(model: str, runs_dir: Path) -> dict[str, object]:
    agent = ReactAgent(model)
    by_id = {task.id: task for task in load_tasks()}
    guardrails: tuple[Guardrail, ...] = ("none", "spotlight", "sanitizer", "policy")
    observations = []
    for attack in ATTACKS:
        task = by_id[attack.task_id]
        for guardrail in guardrails:
            run_id = f"asr-{_slug(model)}-{attack.id}-{guardrail}"
            observed = await measure_attack(task, agent, attack, guardrail, runs_dir, run_id)
            observations.append(observed)
            sys.stderr.write(
                f"{attack.id}/{guardrail}: asr={observed.attack_succeeded} "
                f"util={observed.task_passed}\n"
            )
    rows = security_rows(observations)
    table = security_markdown(rows)
    overall_asr = sum(1 for item in observations if item.attack_succeeded) / len(observations)
    return {
        "model": model,
        "asr": overall_asr,
        "table": table,
        "rows": [
            {
                "guardrail": row.guardrail,
                "category": row.category,
                "trials": row.trials,
                "asr": row.asr,
                "utility": row.utility,
            }
            for row in rows
        ],
    }


def main(argv: list[str]) -> int:
    """Measure ASR for one model and write a results sidecar file."""
    if len(argv) != 2:
        sys.stderr.write("usage: measure_asr.py MODEL\n")
        return 2
    model = argv[1]
    payload = asyncio.run(_run(model, Path("runs")))
    dest = Path("results") / f"{_slug(model)}-asr.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    sys.stdout.write(str(payload["table"]))
    sys.stdout.write(f"\nwrote {dest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
