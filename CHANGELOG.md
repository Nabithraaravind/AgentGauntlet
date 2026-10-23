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
- ReAct agent and cost tracker. `python -m agentgauntlet.runner --agent react` calls a LiteLLM model, including a local Ollama model. Each model call records tokens, latency, and a dollar cost. Ollama is priced at $0 unless a GPU hourly rate is set. Unit tests use a fake model response. A measured retail k=3 run of `ollama/qwen2.5:7b-instruct` scored pass@1 0.467 (`results/ollama-qwen2.5-7b-instruct.json`).
- Travel, calendar and email, and banking worlds, plus 75 tasks. The library is 100 tasks, 25 in each domain. `tasks/validate.py` replays every reference solution.
- Injection suite. Eight attack templates, attack-success and utility rates, and three guardrails: spotlighting, a trigger-line sanitizer, and a rule that blocks a sensitive write the user did not ask for. Tests use a scripted agent and a gullible fake. A measured qwen ASR table scored 0.000 (`results/ollama-qwen2.5-7b-instruct-asr.json`).
- HTML report, Markdown leaderboard, and a compare command. Charts are inline SVG so the report is one file and does not call a CDN.
- `gauntlet` command, `pytest --gauntlet` thresholds, and a composite GitHub Action that writes a Markdown score.
- Experiment list and `docs/results.md`. Measured retail k=3 scores for qwen (pass@1 0.467) and llama3.2:3b (pass@1 0.040) are written up there. Groq was not run (`GROQ_API_KEY` unset).
- Gradio leaderboard over `results/`, MkDocs pages, `CITATION.cff`, and a PyPI release workflow for a `v*` tag. The version in the tree is 0.1.0. Publishing under the name `agentgauntlet` is blocked because that name is already taken on PyPI by an unrelated package.
- `tasks/record_run.py` and `tasks/measure_asr.py` helpers to grade a finished run and to measure the injection table against a real model.
