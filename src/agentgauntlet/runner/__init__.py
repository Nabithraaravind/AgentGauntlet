"""Run tasks in isolated databases and store a trajectory per trial.

Example:
    from agentgauntlet.agents import ScriptedAgent
    from agentgauntlet.runner import RunConfig, run_benchmark
    from agentgauntlet.tasks import load_tasks

    tasks = [task for task in load_tasks() if task.id == "retail-001"]
    summary = await run_benchmark(tasks, ScriptedAgent(), RunConfig(run_id="demo", k=1))
"""

from agentgauntlet.runner.engine import RunConfig, RunSummary, TrialOutcome, run_benchmark

__all__ = ["RunConfig", "RunSummary", "TrialOutcome", "run_benchmark"]
