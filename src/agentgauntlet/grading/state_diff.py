"""Compare a final database with the seed and with ``expected_state``.

A trial passes the state check when every expected row is present and every
write is one of those rows. An extra refund, or a deleted row that was not
replaced, is a side effect.

Example:
    from agentgauntlet.grading import diff_state

    report = diff_state(before, after, task.expected_state)
    report.ok
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

Row = Mapping[str, object]
Table = Sequence[Row]
Snapshot = Mapping[str, Table]


@dataclass(frozen=True)
class StateDiff:
    """What the final database got wrong."""

    missing: list[str]
    side_effects: list[str]

    @property
    def ok(self) -> bool:
        """True when the expected rows are present and nothing else was written."""
        return not self.missing and not self.side_effects


def values_equal(expected: object, actual: object) -> bool:
    """Compare one expected cell to the database value.

    Whole-number floats match integers, so YAML ``2499.00`` equals the integer
    column ``2499``. Booleans stay booleans: ``True`` is not ``1``.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return float(expected) == float(actual)
    return expected == actual


def partial_match(actual: Snapshot, expected: Snapshot) -> list[str]:
    """Return one message per expected row that no unused database row satisfied.

    Each actual row is used at most once, so two identical expected rows require
    two actual rows.
    """
    problems: list[str] = []
    for table, expected_rows in expected.items():
        actual_rows = actual.get(table)
        if actual_rows is None:
            problems.append(f"expected table {table!r} is not in the database")
            continue
        used: set[int] = set()
        for expected_row in expected_rows:
            match = _find_row(actual_rows, expected_row, used)
            if match is None:
                problems.append(f"no unused {table} row matches {dict(expected_row)}")
            else:
                used.add(match)
    return problems


def diff_state(before: Snapshot, after: Snapshot, expected: Snapshot) -> StateDiff:
    """Compare the seed, the final database, and the expected rows.

    A changed row is allowed when an expected row matches it. Each expected row
    covers at most one changed row. If more rows disappeared than appeared, the
    extras were deleted.
    """
    side_effects: list[str] = []
    for table in sorted(set(before) | set(after)):
        added, removed = _changed_rows(before.get(table, ()), after.get(table, ()))
        expected_rows = list(expected.get(table, ()))
        used: set[int] = set()
        for row in added:
            cover = _covering_expected(expected_rows, row, used)
            if cover is None:
                side_effects.append(f"unexpected write in {table}: {dict(row)}")
            else:
                used.add(cover)
        extra_deletes = len(removed) - len(added)
        if extra_deletes > 0:
            side_effects.append(f"unexpected delete in {table}: {extra_deletes} row(s)")
    return StateDiff(missing=partial_match(after, expected), side_effects=side_effects)


def _changed_rows(
    before: Table, after: Table
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    before_left: Counter[str] = Counter(_canonical(row) for row in before)
    after_left: Counter[str] = Counter(_canonical(row) for row in after)
    removed: list[dict[str, object]] = []
    for row in before:
        key = _canonical(row)
        if after_left[key] > 0:
            after_left[key] -= 1
        else:
            removed.append(dict(row))
    added: list[dict[str, object]] = []
    for row in after:
        key = _canonical(row)
        if before_left[key] > 0:
            before_left[key] -= 1
        else:
            added.append(dict(row))
    return added, removed


def _covering_expected(expected_rows: Sequence[Row], actual: Row, used: set[int]) -> int | None:
    for index, expected_row in enumerate(expected_rows):
        if index in used:
            continue
        if _row_covers(expected_row, actual):
            return index
    return None


def _row_covers(expected_row: Row, actual: Row) -> bool:
    return all(
        key in actual and values_equal(expected_row[key], actual[key]) for key in expected_row
    )


def _find_row(actual_rows: Table, expected_row: Row, used: set[int]) -> int | None:
    for index, actual in enumerate(actual_rows):
        if index in used:
            continue
        if _row_covers(expected_row, actual):
            return index
    return None


def _canonical(row: Row) -> str:
    return json.dumps(dict(row), sort_keys=True, default=str)
