"""Replay a reference solution and compare the database to ``expected_state``.

The replay uses the in-memory MCP client, so a wrong argument fails the same
schema check an agent would see.

Example:
    from agentgauntlet.tasks import validate_library

    problems, count = validate_library()
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import Client
from mcp.types import CallToolResult, TextContent

from agentgauntlet.domains.retail import RetailDomain
from agentgauntlet.grading.assertions import check_assertions
from agentgauntlet.grading.state_diff import partial_match, values_equal
from agentgauntlet.tasks.loader import load_tasks
from agentgauntlet.tasks.schema import Difficulty, Task

RETAIL_TASK_COUNT = 25
DIFFICULTY_QUOTA: dict[Difficulty, int] = {"easy": 8, "medium": 10, "hard": 7}
REQUIRED_TAGS = frozenset(
    {
        "lookup",
        "multi-step",
        "policy",
        "refund",
        "refuse",
        "ambiguous",
        "error-recovery",
        "long-horizon",
    }
)
LONG_HORIZON_MIN_CALLS = 8
RETAIL_TABLES = frozenset({"customers", "order_items", "orders", "products", "refunds", "returns"})

# Callers import the matcher from this module. The implementation lives in grading.
__all__ = ["partial_match", "values_equal"]


def check_library(tasks: list[Task]) -> list[str]:
    """Check ids, the retail quota, tags, and that each reference fits ``max_steps``."""
    problems: list[str] = []
    retail = [task for task in tasks if task.domain == "retail"]
    if len(retail) != RETAIL_TASK_COUNT:
        problems.append(f"expected {RETAIL_TASK_COUNT} retail tasks, found {len(retail)}")
    counts = Counter(task.difficulty for task in retail)
    for difficulty, quota in DIFFICULTY_QUOTA.items():
        found = counts[difficulty]
        if found != quota:
            problems.append(f"expected {quota} {difficulty} retail tasks, found {found}")
    seen: set[str] = set()
    tags: set[str] = set()
    for task in tasks:
        tags.update(task.tags)
        if task.id in seen:
            problems.append(f"{task.id}: duplicate id")
        seen.add(task.id)
        call_count = len(task.reference_solution.tool_calls)
        if call_count > task.max_steps:
            problems.append(
                f"{task.id}: reference has {call_count} calls but max_steps is {task.max_steps}"
            )
        if "long-horizon" in task.tags and call_count < LONG_HORIZON_MIN_CALLS:
            problems.append(
                f"{task.id}: long-horizon tasks need at least {LONG_HORIZON_MIN_CALLS} tool calls"
            )
        if task.domain == "retail":
            problems.extend(_unknown_tables(task))
    missing = REQUIRED_TAGS - tags
    if missing:
        problems.append(f"library is missing tags: {', '.join(sorted(missing))}")
    return problems


def validate_library(tasks: list[Task] | None = None) -> tuple[list[str], int]:
    """Load the library if needed, check its shape, and replay every reference solution."""
    loaded = load_tasks() if tasks is None else tasks
    problems = check_library(loaded)
    problems.extend(_collect_replays(loaded))
    # coverage.py loses the trace on the line after asyncio.run returns.
    return problems, len(loaded)  # pragma: no cover


def _collect_replays(tasks: list[Task]) -> list[str]:
    return asyncio.run(_replay_all(tasks))


async def replay_task(task: Task, db_path: Path) -> list[str]:
    """Run one reference solution against a fresh database and return problems."""
    if task.domain != "retail":
        return [f"{task.id}: domain {task.domain!r} has no world yet"]
    domain = RetailDomain(db_path, seed=task.seed)
    domain.setup()
    server = domain.mcp_server()
    # Refused tool calls are part of the reference. The server logs each one at INFO.
    logging.getLogger("mcp.server.mcpserver.server").setLevel(logging.WARNING)
    before = domain.snapshot()
    called: list[str] = []
    problems: list[str] = []
    async with Client(server, raise_exceptions=True) as client:
        for call in task.reference_solution.tool_calls:
            called.append(call.tool)
            result = await client.call_tool(call.tool, dict(call.arguments))
            text = _result_text(result)
            if call.expect_error is None and result.is_error:
                problems.append(f"{task.id}: {call.tool} failed: {text}")
            elif call.expect_error is not None and not result.is_error:
                problems.append(
                    f"{task.id}: {call.tool} succeeded but expected error {call.expect_error}"
                )
            elif call.expect_error is not None and call.expect_error not in text:
                problems.append(
                    f"{task.id}: {call.tool} error {text!r} does not contain {call.expect_error}"
                )
    after = domain.snapshot()
    for mismatch in partial_match(after, task.expected_state):
        problems.append(f"{task.id}: {mismatch}")
    problems.extend(_check_assertions(task, called, before, after))
    return problems


def _unknown_tables(task: Task) -> list[str]:
    problems: list[str] = []
    for table in task.expected_state:
        if table not in RETAIL_TABLES:
            problems.append(f"{task.id}: expected_state table {table!r} is not a retail table")
    for assertion in task.assertions:
        table_name = assertion.table
        if assertion.type == "table_unchanged" and table_name not in RETAIL_TABLES:
            problems.append(f"{task.id}: table_unchanged {table_name!r} is not a retail table")
    return problems


def _check_assertions(
    task: Task,
    called: list[str],
    before: Mapping[str, Sequence[Mapping[str, object]]],
    after: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[str]:
    return [
        failure.message
        for failure in check_assertions(
            task,
            called,
            task.reference_solution.final_answer,
            before,
            after,
        )
    ]


def _result_text(result: CallToolResult) -> str:
    if not result.content:
        return ""
    block = result.content[0]
    if isinstance(block, TextContent):
        return block.text
    return ""


async def _replay_all(tasks: list[Task]) -> list[str]:
    problems: list[str] = []
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for task in tasks:
            try:
                problems.extend(await replay_task(task, root / f"{task.id}.sqlite"))
            except Exception as exc:
                problems.append(f"{task.id}: replay crashed: {type(exc).__name__}: {exc}")
    return problems
