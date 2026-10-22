# AgentGauntlet

AgentGauntlet is pytest for AI agents. It runs your agent through 100 stateful, tool-using tasks on mock MCP servers. It scores task success by checking the final world state, measures how consistent the agent is across repeated trials (pass^k), tracks cost and latency per task, and attacks the agent with a prompt-injection suite. It plugs into CI so a regression fails the build.

[![CI](https://github.com/Nabithraaravind/AgentGauntlet/actions/workflows/ci.yml/badge.svg)](https://github.com/Nabithraaravind/AgentGauntlet/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Headline result:** `ollama/qwen2.5:7b-instruct` on retail, k=3: **pass@1 = 0.467** (bootstrap 95% CI 0.280–0.640), pass^3 = 0.400, ASR = 0.000, cost per success = $0. Run id `qwen-retail-k3`. Numbers are from a real local Ollama run; see `results/ollama-qwen2.5-7b-instruct.json`.

**Status:** the library, runner, grading, ReAct agent, injection suite, HTML report, and `gauntlet` command are in the tree. Four worlds have 25 tasks each. Ruff, mypy, pytest, and `tasks/validate.py` pass locally. The qwen retail k=3 score and its injection ASR table are recorded. Other planned models are still pending. The PyPI name `agentgauntlet` is already taken by an unrelated package, so publishing this project needs a rename or a name transfer before a `v*` tag can land on PyPI.

## Why AgentGauntlet?

- **State-based grading.** A task passes when the agent finishes, the expected database rows are present, and nothing else was written. A task can also require a phrase in the final answer or forbid a tool.
- **Reliability, not just accuracy.** Each task runs k times (default 5). Reports include pass@1, pass^k, and a consistency score.
- **Security built in.** Tool outputs can carry indirect prompt injection. The suite reports attack success rate and whether the original task still gets done, with and without a guardrail.
- **Cost awareness.** Runs log tokens, USD, latency, and tool-call counts, including a cost-versus-success view.

## Quickstart

Install from a checkout. `pip install agentgauntlet` works after the release workflow publishes a `v*` tag.

```bash
uv sync
uv run pytest
uv run python tasks/validate.py
uv run gauntlet run --tasks retail-001 --k 1 --run-id smoke
uv run gauntlet report runs/smoke --html
```

`gauntlet run` uses the scripted agent. Add `--agent react --model ollama/qwen2.5:7b-instruct` to call a local model.

## Results

| Model | pass@1 | pass^3 | ASR | Cost / success | Run |
| --- | ---: | ---: | ---: | ---: | --- |
| ollama/qwen2.5:7b-instruct | 0.467 | 0.400 | 0.000 | $0 | `qwen-retail-k3` |

Retail only, k=3, 25 tasks, 75 trials. Dominant failure tags: gave_up (11), step_limit (9), policy_violation (8), wrong_args (6). pass^5 is 0 because k was 3. ASR is from 8 attacks × 4 guardrails (32 trials); the model never wrote an attacker row, and utility under attack was also 0 on those lookup tasks. Other planned models are not graded yet.

## Security

Eight indirect-injection templates cover a direct override, a fake system line, role-play, a base64 payload, data exfiltration, a tool hijack, a delayed trigger, and Hindi/Hinglish. Attack success means the attacker's database row appeared. Utility means the original task still passed.

The guardrails are none, spotlighting, a sanitizer that drops trigger lines, and a rule that blocks a sensitive write the user did not ask for. In unit tests, a gullible agent that obeys the trigger is stopped by the sanitizer and by that rule. On `ollama/qwen2.5:7b-instruct`, ASR was 0.000 across all eight attacks and four guardrails (`results/ollama-qwen2.5-7b-instruct-asr.json`). Utility under those attack trials was also 0.000.

## Architecture

The command line, the runner, the four worlds, grading, the injection suite, and the HTML report are in the package. The Gradio app reads `results/` and does not call a model.

```mermaid
flowchart LR
    CLI["CLI / pytest plugin"] --> Runner
    Runner --> Agent
    Runner --> Sandbox
    Sandbox --> Domain["Domain MCP server + SQLite"]
    Agent --> Domain
    Runner --> Grading
    Grading --> Report["HTML / markdown report"]
    Security["Injection suite + guardrails"] --> Runner
    Cost["Cost tracker"] --> Report
```

## Custom tasks, domains, and agents

See [examples/README.md](examples/README.md) and the docs pages for tasks, domains, and agents. `gauntlet init` writes a starter gate file.

## CI

This repository's workflow (`.github/workflows/ci.yml`) runs ruff, mypy, and pytest on Python 3.11 and 3.12.

`action.yml` is the reusable action. This repository calls it from `.github/workflows/gauntlet.yml`.

```yaml
- uses: Nabithraaravind/AgentGauntlet@v1
  with:
    subset: retail-001
    k: "1"
```

`pytest --gauntlet --gauntlet-config gauntlet.yaml` exits if a threshold is missed. The scripted agent is what that gate runs.

## Methodology and limitations

Grading compares the final database to a partial expected state and flags unexpected writes. pass^k is `C(c, k) / C(n, k)`. Mock worlds are not production tools: a refund that the retail rules reject cannot land, so an attack that the rules refuse is not a successful attack. Nothing in this file is a measured model claim.

## What didn't work

The first `ollama pull qwen2.5:7b-instruct` failed mid-download with a DNS error against Cloudflare R2; a retry succeeded. A smoke trial of `llama3.2:3b` on retail-001 hit the step limit after getting the right order status and never returned a final answer. Publishing to PyPI under the name `agentgauntlet` is blocked: that name is already taken on PyPI by an unrelated chaos-engineering package at version 0.2.0. Groq was not run because `GROQ_API_KEY` is not set. A 30 second trial timeout also expired once when two full pytest processes ran at the same time; that timeout was not changed.

## Roadmap

| Milestone | Delivers | State |
| --- | --- | --- |
| M1 | Scaffold, lint, types, CI | Local checks green |
| M2 | Domain base and retail MCP world | Local checks green |
| M3 | Task schema and 25 retail tasks | Local checks green |
| M4 | Scripted agent and runner | Local checks green |
| M5 | State grading and pass^k | Local checks green |
| M6 | ReAct agent, Ollama, cost | Measured: qwen retail k=3 pass@1 0.467 |
| M7 | Four domains, 100 tasks | Local checks green |
| M8 | Injection suite and guardrails | qwen ASR 0.000 recorded |
| M9 | HTML report and compare | Local checks green |
| M10 | pytest plugin and GitHub Action | Local checks green |
| M11 | Measured runs on 4–6 models | qwen recorded; other models pending |
| M12 | Gradio app, docs site, PyPI v0.1.0 | App and docs in tree; PyPI name taken |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Decisions that are easy to miss are in [docs/decisions.md](docs/decisions.md).

## Citation

See [CITATION.cff](CITATION.cff).

## License

[MIT](LICENSE).
