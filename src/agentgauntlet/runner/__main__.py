"""Run an agent from the command line.

The default agent is scripted, so CI does not need a model. ``--agent react``
calls a LiteLLM model. A local Ollama model needs no API key.

Example:
    python -m agentgauntlet.runner --run-id smoke --k 1 --tasks retail-001
    python -m agentgauntlet.runner --agent react --k 3 --tasks retail --timeout 300
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from agentgauntlet.agents import ReactAgent, ScriptedAgent
from agentgauntlet.agents.base import Agent
from agentgauntlet.runner.engine import RunConfig, format_summary, run_benchmark
from agentgauntlet.tasks import load_tasks
from agentgauntlet.tasks.schema import Task


def main(argv: list[str] | None = None) -> int:
    """Run the scripted agent. Return 0 when every trial completed."""
    return asyncio.run(_main(argv))


async def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agentgauntlet.runner")
    parser.add_argument("--run-id", default="scripted")
    parser.add_argument("--agent", choices=["scripted", "react"], default="scripted")
    parser.add_argument("--model", default="ollama/qwen2.5:7b-instruct")
    parser.add_argument("--gpu-usd-per-hour", type=float, default=0)
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
    summary = await run_benchmark(selected, _agent(args), config)
    sys.stderr.write(format_summary(summary) + "\n")
    if all(trial.status == "completed" for trial in summary.trials):
        return 0
    return 1


def _agent(args: argparse.Namespace) -> Agent:
    if args.agent == "react":
        api_base = os.environ.get("OLLAMA_API_BASE")
        return ReactAgent(
            str(args.model),
            api_base=api_base or None,
            gpu_usd_per_hour=float(args.gpu_usd_per_hour),
        )
    return ScriptedAgent()


def _select(spec: str, tasks: list[Task]) -> list[Task]:
    domains = {"retail", "travel", "calendar_email", "banking"}
    if spec in domains:
        return [task for task in tasks if task.domain == spec]
    return [task for task in tasks if task.id == spec]


if __name__ == "__main__":
    raise SystemExit(main())
