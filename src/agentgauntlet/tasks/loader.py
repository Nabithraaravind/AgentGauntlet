"""Load task YAML files into :class:`Task` models.

Example:
    from agentgauntlet.tasks import load_tasks

    tasks = load_tasks()
    retail = [task for task in tasks if task.domain == "retail"]
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from agentgauntlet.tasks.schema import Task


class TaskLoadError(Exception):
    """A task file is missing, unreadable, or does not match the schema."""


def library_dir() -> Path:
    """Return the packaged directory that holds ``*.yaml`` tasks."""
    return Path(__file__).resolve().parent / "library"


def load_tasks(directory: Path | None = None) -> list[Task]:
    """Load every ``*.yaml`` file in ``directory``, sorted by filename.

    The default directory is the packaged library. The task ``id`` must match
    the filename stem, so ``retail-001.yaml`` is the only legal name for that id.
    """
    folder = library_dir() if directory is None else directory
    paths = sorted(folder.glob("*.yaml"))
    if not paths:
        raise TaskLoadError(f"No tasks in {folder}")
    return [parse_task(path) for path in paths]


def parse_task(path: Path) -> Task:
    """Parse one task file."""
    data = _read_mapping(path)
    try:
        task = Task.model_validate(data)
    except ValidationError as exc:
        raise TaskLoadError(f"{path}:\n{exc}") from exc
    if path.stem != task.id:
        raise TaskLoadError(f"{path}: id {task.id} does not match the filename")
    return task


def _read_mapping(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaskLoadError(f"{path}: {exc}") from exc
    loaded: object = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise TaskLoadError(f"{path}: task file must be a mapping")
    mapping: dict[str, object] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise TaskLoadError(f"{path}: mapping keys must be strings")
        mapping[key] = value
    return mapping
