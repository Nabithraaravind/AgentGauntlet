"""Run the scripted agent from the command line.

Example:
    python -m agentgauntlet.runner --run-id smoke --k 1 --tasks retail-001
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError

from agentgauntlet.agents import ScriptedAgent
from agentgauntlet.runner.engine import RunConfig, format_summary, run_benchmark
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Task


def main(argv: list[str] | None = None) -> int:
    """Run the scripted agent. Return 0 when every trial completed."""
    return asyncio.run(_main(argv))


async def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agentgauntlet.runner")
    parser.add_argument("--run-id", default="scripted")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--tasks", default="retail", help="A domain name or one task id.")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    try:
        config = RunConfig(
            run_id=str(args.run_id),
            runs_dir=args.runs_dir,
            k=args.k,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout,
        )
    except ValidationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    selected = _select(str(args.tasks), load_tasks())
    if not selected:
        sys.stderr.write(f"No tasks match {args.tasks}.\n")
        return 1
    summary = await run_benchmark(selected, ScriptedAgent(), config)
    sys.stderr.write(format_summary(summary) + "\n")
    if all(trial.status == "completed" for trial in summary.trials):
        return 0
    return 1


def _select(spec: str, tasks: list[Task]) -> list[Task]:
    domains = {"retail", "travel", "calendar_email", "banking"}
    if spec in domains:
        return [task for task in tasks if task.domain == spec]
    return [task for task in tasks if task.id == spec]


if __name__ == "__main__":
    raise SystemExit(main())
