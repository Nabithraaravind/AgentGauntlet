# Architecture decisions

Short log of choices that would otherwise be invisible. Newest entries at the bottom. Each one is a default picked so work can continue.

## ADR-001: uv, hatchling, and a src layout

**Status:** accepted (M1)

The package lives in `src/agentgauntlet` and is built with hatchling. uv manages the lockfile and the virtualenv. A `src` layout means tests import the installed package, not a checkout sitting on `sys.path` by accident.

## ADR-002: Version stays `0.1.0.dev0` until the PyPI release

**Status:** accepted (M1)

`pyproject.toml` is the only version field. `agentgauntlet.__version__` reads it back through `importlib.metadata`. The public `v0.1.0` release is milestone M12. Until then the version is a dev release so a scaffold is not published as `0.1.0`.

## ADR-003: ruff, mypy strict, and an 85% coverage gate

**Status:** accepted (M1)

- Line length is 100. Docstrings use the Google convention.
- Modules start with `from __future__ import annotations` so annotations stay consistent once the code has forward references.
- `mypy --strict` covers `src/agentgauntlet` and `tests`.
- `pytest` fails under 85% line coverage of the installed package. The gate is on `agentgauntlet`, not on tests or future example scripts.
- CI runs ruff, mypy, and pytest. Pre-commit runs ruff and the file-hygiene hooks so the slow type check stays a single CI job.

## ADR-004: No runtime dependencies and no console script yet

**Status:** accepted (M1)

`dependencies` is empty. Typer, MCP, LiteLLM, and the rest arrive in the milestone that imports them. There is no `gauntlet` entry point until `cli.py` exists. An entry point that imports a missing module would make `uv sync` fail.

## ADR-005: CI installs the uv version that wrote `uv.lock`

**Status:** accepted (M1)

GitHub Actions installs uv `0.11.33` (the version used to generate the lockfile) and runs `uv sync --locked`. A newer uv can rewrite the lock header and fail `--locked`. When uv is bumped, regenerate `uv.lock` and update the pin in `.github/workflows/ci.yml` in the same change.

## ADR-006: Local runs are gitignored, published results are not

**Status:** accepted (M1)

`runs/` is gitignored. It will hold trajectories and local reports. `results/` is not ignored: milestone M11 will commit the real experiment snapshots the Gradio app loads. Nothing measured is written into the docs before those files exist.

## ADR-007: MCP Python SDK v2

**Status:** accepted (M2)

The official `mcp` package is v2. The high-level server class is `MCPServer` (`mcp.server.MCPServer`). v1 called it `FastMCP`; that import path is gone. Tools are still plain functions with `@server.tool()`, and the JSON schema still comes from the type hints. Tests use `mcp.Client` on the server object, which is the SDK's in-memory client. One test also launches `python -m agentgauntlet.domains.retail` and talks to it over stdio, because that is how a host will run the server.

## ADR-008: Retail money, clock, and the fixed spine

**Status:** accepted (M2)

Prices and refunds are integer rupees. There are no paise, so snapshots do not depend on binary floats. The world date is 2026-10-01, not the wall clock, so "within 30 days" does not rot. Every seed contains the same customers `C001`–`C003`, products, and orders `A1043`–`A1047`. Order `A1043` is the partial-return case (headphones `HP-220` at 2499 INR and charger `CH-110`). Faker's `en_IN` locale, pinned in `uv.lock`, adds four more customers and three more orders. A task can name a spine id and still get a deterministic database.

## ADR-009: Tool failures are DomainError, flaky mode does not sleep

**Status:** accepted (M2)

A business-rule failure raises `DomainError(code, message)`. The MCP wrapper turns it into `ToolError`, so the client sets `is_error` and the model reads `code: message`. Flaky mode draws from a second seeded RNG and raises `timeout` or `internal` before any SQL. It does not sleep and it does not write. The rate defaults to 0.

## ADR-010: Expected state is a partial database match

**Status:** accepted (M3)

`expected_state` keys are SQLite column names. A refund row uses `amount_inr` (an integer number of rupees), not `amount`. The checker walks each expected row and claims one unused actual row. Extra columns and extra rows are allowed. A whole-number float such as `2499.0` equals the integer `2499`. `true` does not equal `1`.

The reference solution is replayed with the in-memory MCP client, the same client the unit tests use. A call may set `expect_error` to the stable code it should hit, such as `return_window_closed`. Two assertion types sit beside the spec's three: `tool_called`, and `table_unchanged` for a table that must stay at its seeded contents.

Task YAML lives only in `src/agentgauntlet/tasks/library`, inside the package, so the wheel picks it up. There is no second copy at the repo root. `mypy --strict` also covers `tasks/validate.py`.

## ADR-011: The first 25 retail tasks are 8 easy, 10 medium, 7 hard

**Status:** accepted (M3)

The quota is checked, not left as a comment. Every task uses seed 17. Easy tasks allow 5 tool calls, medium 10, hard 15. A `long-horizon` task's reference solution has at least 8 calls. `retail-017` is the partial headphone return on order `A1043`: return `HP-220`, refund 2499 to the original payment, leave the charger, and do not cancel the order.

## ADR-012: The scripted runner finishes a trial before grading it

**Status:** accepted (M4)

The scripted agent plays `reference_solution` and does not call a model. Each trial copies a template SQLite file, so trials do not share writes. The transcript is `runs/<run_id>/<task_id>/trial-NN.jsonl`. The last line is a result. Resume skips a file that already has one. A crash before that line leaves the trial unfinished, and the next start runs it again.

`completed` means the agent returned a final answer. It does not mean the database matched. That check is grading (M5). Tool retries default to 0 so a scripted error stays in the file. The trial transport is the in-memory MCP client. `python -m agentgauntlet.runner` is the command for this milestone. The Typer `gauntlet` command is still later, so there is still no console script.

## ADR-013: A trial passes on the database, and pass^k is the unbiased ratio

**Status:** accepted (M5)

Grading reads the template database and the trial database. `expected_state` rows must be present. A changed or inserted row is allowed only when an unused expected row matches it, so an extra refund is a side effect. A pure deletion, where more rows disappeared than appeared, is a side effect too. Replacing a row is not also counted as a delete.

`passed` requires status `completed`, a clean state diff, and no failed assertion. The failure tag is the first match: step limit, timeout or error, a forbidden tool, an unrecovered tool error, arguments that match no reference call, a tool the reference never uses, then a finished agent whose database is still wrong. Anything else is `wrong_tool`.

pass^k is `C(c, k) / C(n, k)`. pass@1 is `c / n`, the same as pass^1. Overall scores average tasks, not trials. Consistency is 1 minus the population variance of the 0/1 outcomes. The 95% interval resamples tasks and takes the 2.5 and 97.5 linear percentiles. These formulas are locked to hand-computed examples in the tests. No model score is published from them.



