"""Task schema, loader, and reference-solution replay."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

import pytest
import yaml
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from agentgauntlet.domains.retail import RetailDomain
from agentgauntlet.tasks.loader import TaskLoadError, load_tasks, parse_task
from agentgauntlet.tasks.replay import (
    RETAIL_TABLES,
    _check_assertions,
    _replay_all,
    _result_text,
    check_library,
    partial_match,
    replay_task,
    validate_library,
    values_equal,
)
from agentgauntlet.tasks.schema import Assertion, Task


class _ValidatorCli(Protocol):
    """The bits of ``tasks/validate.py`` the tests replace."""

    validate_library: Callable[[], tuple[list[str], int]]
    TaskLoadError: type[BaseException]

    def main(self) -> int:
        """Run the validator."""
        ...


def _cli() -> _ValidatorCli:
    path = Path(__file__).resolve().parents[2] / "tasks" / "validate.py"
    spec = importlib.util.spec_from_file_location("task_validate_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_ValidatorCli", module)


def _sample() -> Task:
    return next(task for task in load_tasks() if task.id == "retail-012")


def test_partial_match_uses_each_row_once() -> None:
    """A row cannot satisfy two expected rows, and 2499.0 matches the integer 2499."""
    actual = {"orders": [{"id": "A1043", "status": "delivered", "extra": 1}]}
    assert partial_match(actual, {"orders": [{"id": "A1043", "status": "delivered"}]}) == []
    reused = partial_match(
        actual,
        {"orders": [{"id": "A1043"}, {"id": "A1043"}]},
    )
    assert len(reused) == 1
    assert "no unused" in reused[0]
    assert partial_match(actual, {"refunds": [{"amount_inr": 1}]}) == [
        "expected table 'refunds' is not in the database"
    ]
    assert values_equal(2499.0, 2499)
    assert not values_equal(1.5, 2)
    assert values_equal(True, True)
    assert not values_equal(True, 1)
    assert not values_equal(1, True)
    assert values_equal("delivered", "delivered")
    assert not values_equal("delivered", "shipped")
    missing_column = partial_match(actual, {"orders": [{"missing": 1}]})
    assert len(missing_column) == 1


def test_schema_rejects_bad_difficulty_and_incomplete_assertions() -> None:
    """Unknown difficulties and checks that omit their field never enter the library."""
    task = _sample()
    payload = task.model_dump()
    payload["difficulty"] = "impossible"
    with pytest.raises(ValidationError):
        Task.model_validate(payload)
    with pytest.raises(ValidationError, match="tool_not_called requires tool"):
        Assertion.model_validate({"type": "tool_not_called", "value": 1})
    with pytest.raises(ValidationError, match="max_tool_calls requires value"):
        Assertion.model_validate({"type": "max_tool_calls"})
    with pytest.raises(ValidationError, match="final_answer_contains requires any_of"):
        Assertion.model_validate({"type": "final_answer_contains", "any_of": []})
    with pytest.raises(ValidationError, match="does not use value"):
        Assertion.model_validate({"type": "tool_called", "tool": "get_order", "value": 1})
    with pytest.raises(ValidationError, match="table_unchanged requires table"):
        Assertion.model_validate({"type": "table_unchanged", "tool": "get_order"})


def test_loader_rejects_bad_files(tmp_path: Path) -> None:
    """A bad file names itself in the error and does not stop the message at 'invalid'."""
    with pytest.raises(TaskLoadError, match="No tasks"):
        load_tasks(tmp_path)

    listed = tmp_path / "retail-099.yaml"
    listed.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(TaskLoadError, match="must be a mapping"):
        parse_task(listed)

    numbered = tmp_path / "keys.yaml"
    numbered.write_text(yaml.safe_dump({1: "x"}), encoding="utf-8")
    with pytest.raises(TaskLoadError, match="keys must be strings"):
        parse_task(numbered)

    missing = tmp_path / "retail-098.yaml"
    missing.write_text("id: retail-098\n", encoding="utf-8")
    with pytest.raises(TaskLoadError, match="retail-098"):
        parse_task(missing)

    copied = tmp_path / "retail-099.yaml"
    renamed = _sample().model_copy(update={"id": "retail-002"})
    copied.write_text(yaml.safe_dump(renamed.model_dump()), encoding="utf-8")
    with pytest.raises(TaskLoadError, match="does not match the filename"):
        parse_task(copied)

    with pytest.raises(TaskLoadError, match="retail-098"):
        parse_task(tmp_path / "retail-098")


def test_retail_table_names_match_a_live_snapshot(tmp_path: Path) -> None:
    """Expected-state keys are the real tables, so a renamed table fails this test."""
    domain = RetailDomain(tmp_path / "world.sqlite", seed=17)
    domain.setup()
    assert set(domain.snapshot()) == RETAIL_TABLES


def test_check_library_reports_quota_duplicates_and_unknown_tables() -> None:
    """Shape checks name the task and do not stop at the first problem."""
    base = _sample()
    clone = base.model_copy(
        update={
            "tags": ["long-horizon"],
            "max_steps": 2,
            "expected_state": {"ledgers": [{"id": "x"}]},
            "assertions": [Assertion(type="table_unchanged", table="vault")],
        }
    )
    travel = base.model_copy(update={"domain": "travel", "id": "travel-001"})
    problems = check_library([base, clone, travel])
    text = "\n".join(problems)
    assert "expected 25 retail tasks, found 2" in text
    assert "expected 8 easy retail tasks, found 0" in text
    assert "retail-012: duplicate id" in text
    assert "max_steps is 2" in text
    assert "long-horizon" in text
    assert "ledgers" in text
    assert "vault" in text
    assert "library is missing tags" in text


def test_assertions_flag_a_reference_that_breaks_its_own_rules() -> None:
    """Forbidden tools, missing phrases, and a changed table are all reported."""
    task = _sample()
    before: dict[str, list[Mapping[str, object]]] = {"refunds": []}
    after: dict[str, list[Mapping[str, object]]] = {"refunds": [{"amount_inr": 1}]}
    checks = [
        Assertion(type="tool_not_called", tool="get_order"),
        Assertion(type="tool_called", tool="get_policy"),
        Assertion(type="max_tool_calls", value=1),
        Assertion(type="final_answer_contains", any_of=["missing-phrase"]),
        Assertion(type="table_unchanged", table="refunds"),
    ]
    broken = task.model_copy(update={"assertions": checks})
    problems = _check_assertions(broken, ["get_order", "create_return"], before, after)
    assert len(problems) == 5


async def test_replay_reports_unreachable_state_and_wrong_errors(tmp_path: Path) -> None:
    """A reference that cancels a delivered order, or expects the wrong code, is a problem."""
    task = next(item for item in load_tasks() if item.id == "retail-001")
    travel = task.model_copy(update={"domain": "travel", "id": "travel-001"})
    assert await replay_task(travel, tmp_path / "travel.sqlite") == [
        "travel-001: domain 'travel' has no world yet"
    ]

    cancelled = task.model_copy(
        update={"expected_state": {"orders": [{"id": "A1043", "status": "cancelled"}]}}
    )
    mismatch = await replay_task(cancelled, tmp_path / "mismatch.sqlite")
    assert any("cancelled" in problem for problem in mismatch)

    surprised = task.model_copy(
        update={
            "reference_solution": task.reference_solution.model_copy(
                update={
                    "tool_calls": [
                        task.reference_solution.tool_calls[0].model_copy(
                            update={"expect_error": "not_found"}
                        )
                    ]
                }
            )
        }
    )
    unexpected = await replay_task(surprised, tmp_path / "ok.sqlite")
    assert any("succeeded but expected error not_found" in problem for problem in unexpected)

    wrong_code = task.model_copy(
        update={
            "reference_solution": task.reference_solution.model_copy(
                update={
                    "tool_calls": [
                        task.reference_solution.tool_calls[0].model_copy(
                            update={"tool": "cancel_order", "expect_error": "not_found"}
                        )
                    ]
                }
            )
        }
    )
    coded = await replay_task(wrong_code, tmp_path / "code.sqlite")
    assert any("does not contain not_found" in problem for problem in coded)

    failed = task.model_copy(
        update={
            "reference_solution": task.reference_solution.model_copy(
                update={
                    "tool_calls": [
                        task.reference_solution.tool_calls[0].model_copy(
                            update={"tool": "cancel_order"}
                        )
                    ]
                }
            )
        }
    )
    blown = await replay_task(failed, tmp_path / "fail.sqlite")
    assert any("cancel_order failed" in problem for problem in blown)


def test_validate_library_accepts_every_retail_task() -> None:
    """Every packaged reference solution reaches its expected state."""
    problems, count = validate_library()
    assert problems == []
    assert count == 25


async def test_replay_all_records_an_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bug inside one replay is recorded so the rest of the library still runs."""

    async def explode(task: Task, db_path: Path) -> list[str]:
        raise RuntimeError(f"disk full while replaying {task.id} at {db_path.name}")

    monkeypatch.setattr("agentgauntlet.tasks.replay.replay_task", explode)
    task = next(item for item in load_tasks() if item.id == "retail-001")
    problems = await _replay_all([task])
    assert problems == [
        "retail-001: replay crashed: RuntimeError: "
        "disk full while replaying retail-001 at retail-001.sqlite"
    ]


def test_cli_reports_problems_and_a_clean_library(capsys: pytest.CaptureFixture[str]) -> None:
    """The script writes problems to stderr and returns the matching status code."""
    module = _cli()
    module.validate_library = lambda: (["retail-001: bad"], 1)
    assert module.main() == 1
    assert "retail-001: bad" in capsys.readouterr().err

    module.validate_library = lambda: ([], 25)
    assert module.main() == 0
    assert "Validated 25 tasks." in capsys.readouterr().err

    def explode() -> tuple[list[str], int]:
        raise module.TaskLoadError("broken library")

    module.validate_library = explode
    assert module.main() == 1
    assert "broken library" in capsys.readouterr().err


def test_result_text_ignores_empty_and_non_text_blocks() -> None:
    """Only a text block is shown to the reference checker."""
    assert _result_text(CallToolResult(content=[], is_error=False)) == ""
    image = CallToolResult.model_validate(
        {"content": [{"type": "image", "data": "aa", "mimeType": "image/png"}], "isError": False}
    )
    assert _result_text(image) == ""
    text = CallToolResult(content=[TextContent(type="text", text="not_delivered")], is_error=False)
    assert _result_text(text) == "not_delivered"
