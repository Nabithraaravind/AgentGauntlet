# Changelog

All notable changes to AgentGauntlet are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository scaffold: uv, hatchling `src` layout, ruff, mypy `--strict`, pytest with an 85% coverage gate, pre-commit, and a CI workflow for Python 3.11 and 3.12.
- Retail mock world: SQLite schema, seeded orders, a support policy, and eight MCP tools. Unit tests call every tool through an MCP client, including one stdio subprocess.
- Task schema, loader, and 25 retail tasks. `tasks/validate.py` replays each reference solution through the MCP client and checks the expected database state.
- Scripted agent and runner. Each trial gets its own database copy. Trajectories are JSONL under `runs/`, and a finished trial is skipped when the same run id is started again. `python -m agentgauntlet.runner` plays the retail reference solutions.
- State grading and metrics. A trial passes when the agent finishes, the expected rows are present, and no extra database writes appeared. Reports include pass@1, pass^k, consistency, cost per success, a failure tag, and a bootstrap interval on pass@1. The metric tests use hand-computed examples.
