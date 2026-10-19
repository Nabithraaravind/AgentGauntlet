"""Task documents: what the user wants, what the database must look like, and a known solution.

Example:
    from agentgauntlet.tasks import Task

    task = Task.model_validate(
        {
            "id": "retail-001",
            "domain": "retail",
            "difficulty": "easy",
            "tags": ["lookup"],
            "user_goal": "What is the status of order A1043?",
            "user_persona": "brief and precise",
            "seed": 17,
            "max_steps": 5,
            "expected_state": {"orders": [{"id": "A1043", "status": "delivered"}]},
            "reference_solution": {
                "final_answer": "Order A1043 is delivered.",
                "tool_calls": [{"tool": "get_order", "arguments": {"order_id": "A1043"}}],
            },
        }
    )
"""

from __future__ import annotations

from typing import Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonScalar: TypeAlias = str | int | float | bool | None
DomainName: TypeAlias = Literal["retail", "travel", "calendar_email", "banking"]
Difficulty: TypeAlias = Literal["easy", "medium", "hard"]
AssertionType: TypeAlias = Literal[
    "tool_not_called",
    "tool_called",
    "max_tool_calls",
    "final_answer_contains",
    "table_unchanged",
]


class ToolCall(BaseModel):
    """One call in a reference solution.

    ``expect_error`` is the stable error code when this call is supposed to
    fail, such as ``cannot_cancel``. A call without it must succeed.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    arguments: dict[str, JsonScalar] = Field(default_factory=dict)
    expect_error: str | None = None


class Assertion(BaseModel):
    """A check on the reference trajectory, beyond the database diff.

    ``final_answer_contains`` passes when any string in ``any_of`` appears in
    the final answer, ignoring case. ``table_unchanged`` passes when that
    table is identical to the seeded database.
    """

    model_config = ConfigDict(extra="forbid")

    type: AssertionType
    tool: str | None = None
    value: int | None = None
    any_of: list[str] | None = None
    table: str | None = None

    @model_validator(mode="after")
    def required_fields(self) -> Self:
        """Reject a check that is missing the field it reads."""
        if self.type in {"tool_not_called", "tool_called"}:
            self._require(self.tool is not None, "tool")
            self._reject_unused(value=self.value, any_of=self.any_of, table=self.table)
        elif self.type == "max_tool_calls":
            self._require(self.value is not None and self.value >= 1, "value >= 1")
            self._reject_unused(tool=self.tool, any_of=self.any_of, table=self.table)
        elif self.type == "final_answer_contains":
            self._require(bool(self.any_of), "any_of")
            self._reject_unused(tool=self.tool, value=self.value, table=self.table)
        else:
            self._require(self.table is not None, "table")
            self._reject_unused(tool=self.tool, value=self.value, any_of=self.any_of)
        return self

    def _require(self, ok: bool, field: str) -> None:
        if not ok:
            raise ValueError(f"{self.type} requires {field}")

    def _reject_unused(self, **fields: object) -> None:
        used = [name for name, present in fields.items() if present is not None]
        if used:
            raise ValueError(f"{self.type} does not use {', '.join(used)}")


class ReferenceSolution(BaseModel):
    """A known sequence of tool calls that reaches ``expected_state``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tool_calls: list[ToolCall] = Field(min_length=1)
    final_answer: str = Field(min_length=1)


class Task(BaseModel):
    """One benchmark item.

    ``expected_state`` is a partial match: every listed row must appear, and
    only the listed columns are compared. Field names are database columns.
    Refund amounts use ``amount_inr`` (whole rupees), not ``amount``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z]+-[0-9]{3}$")
    domain: DomainName
    difficulty: Difficulty
    tags: list[str] = Field(min_length=1)
    user_goal: str = Field(min_length=1)
    user_persona: str = Field(min_length=1)
    seed: int = Field(ge=0)
    max_steps: int = Field(ge=1)
    expected_state: dict[str, list[dict[str, JsonScalar]]] = Field(min_length=1)
    assertions: list[Assertion] = Field(default_factory=list)
    reference_solution: ReferenceSolution
