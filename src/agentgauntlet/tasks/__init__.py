"""Benchmark tasks and the check that each reference solution is solvable.

Example:
    from agentgauntlet.tasks import load_tasks, validate_library

    tasks = load_tasks()
    problems, count = validate_library(tasks)
"""

from agentgauntlet.tasks.loader import TaskLoadError, load_tasks
from agentgauntlet.tasks.replay import validate_library
from agentgauntlet.tasks.schema import Task

__all__ = ["Task", "TaskLoadError", "load_tasks", "validate_library"]
