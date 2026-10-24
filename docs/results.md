# Results

Measured retail runs (k=3, 25 tasks, 75 trials) are recorded below. Numbers come only from finished local runs.

## Summary

| Model | pass@1 | pass^3 | ASR | Cost / success | Run |
| --- | ---: | ---: | ---: | ---: | --- |
| ollama/qwen2.5:7b-instruct | 0.467 | 0.400 | 0.000 | $0 | `qwen-retail-k3` |
| ollama/phi3:mini | 0.280 | 0.280 | — | $0 | `phi3-retail-k3` |
| ollama/llama3.2:3b | 0.040 | 0.040 | — | $0 | `llama32-retail-k3` |
| ollama/llama3.1:8b | 0.040 | 0.040 | — | $0 | `llama31-retail-k3` |
| ollama/mistral-nemo | 0.040 | 0.040 | — | $0 | `mistral-nemo-retail-k3` |

All five planned Ollama models are graded. `groq/llama-3.1-8b-instant` was not run because `GROQ_API_KEY` is unset.

## ollama/qwen2.5:7b-instruct

Command:

```bash
uv run gauntlet run --agent react --model ollama/qwen2.5:7b-instruct --tasks retail --k 3 --run-id qwen-retail-k3 --timeout 300
```

Graded from `runs/qwen-retail-k3` into `results/ollama-qwen2.5-7b-instruct.json`:

| Metric | Value |
| --- | ---: |
| pass@1 | 0.467 |
| bootstrap 95% CI | 0.280 – 0.640 |
| pass^2 | 0.427 |
| pass^3 | 0.400 |
| pass^5 | 0.000 (k was 3) |
| cost per success | $0.00 |
| ASR (8 attacks × 4 guardrails) | 0.000 |
| utility under attack | 0.000 |
| tasks / trials | 25 / 75 |
| trials that returned a final answer | 55 |

Failure tags: gave_up 11, step_limit 9, policy_violation 8, wrong_args 6, tool_error_not_recovered 3, wrong_tool 3.

The injection table is in `results/ollama-qwen2.5-7b-instruct-asr.json`. Every cell is ASR 0.00 / utility 0.00.

## ollama/llama3.2:3b

Command:

```bash
uv run gauntlet run --agent react --model ollama/llama3.2:3b --tasks retail --k 3 --run-id llama32-retail-k3 --timeout 300
```

Graded from `runs/llama32-retail-k3` into `results/ollama-llama3.2-3b.json`:

| Metric | Value |
| --- | ---: |
| pass@1 | 0.040 |
| bootstrap 95% CI | 0.000 – 0.120 |
| pass^2 | 0.040 |
| pass^3 | 0.040 |
| pass^5 | 0.000 (k was 3) |
| cost per success | $0.00 |
| ASR | not measured |
| tasks / trials | 25 / 75 |
| trials that returned a final answer | 12 |

Failure tags: step_limit 43, gave_up 20, wrong_args 3, tool_error_not_recovered 3, hallucinated_success 3. The model often called tools until the step limit without returning a final answer.

## ollama/phi3:mini

Command:

```bash
uv run gauntlet run --agent react --model ollama/phi3:mini --tasks retail --k 3 --run-id phi3-retail-k3 --timeout 300
```

Graded from `runs/phi3-retail-k3` into `results/ollama-phi3-mini.json`:

| Metric | Value |
| --- | ---: |
| pass@1 | 0.280 |
| bootstrap 95% CI | 0.120 – 0.440 |
| pass^2 | 0.280 |
| pass^3 | 0.280 |
| pass^5 | 0.000 (k was 3) |
| cost per success | $0.00 |
| ASR | not measured |
| tasks / trials | 25 / 75 |
| trials that returned a final answer | 30 |

Failure tags: step_limit 39, gave_up 6, hallucinated_success 6, wrong_tool 3.

## ollama/llama3.1:8b

Command:

```bash
uv run gauntlet run --agent react --model ollama/llama3.1:8b --tasks retail --k 3 --run-id llama31-retail-k3 --timeout 300
```

Graded from `runs/llama31-retail-k3` into `results/ollama-llama3.1-8b.json`:

| Metric | Value |
| --- | ---: |
| pass@1 | 0.040 |
| bootstrap 95% CI | 0.000 – 0.160 |
| pass^2 | 0.040 |
| pass^3 | 0.040 |
| pass^5 | 0.000 (k was 3) |
| cost per success | $0.00 |
| ASR | not measured |
| tasks / trials | 25 / 75 |
| trials that returned a final answer | 4 |

Failure tags: step_limit 48, gave_up 23, policy_violation 1.

## ollama/mistral-nemo

Command:

```bash
uv run gauntlet run --agent react --model ollama/mistral-nemo --tasks retail --k 3 --run-id mistral-nemo-retail-k3 --timeout 300
```

Graded from `runs/mistral-nemo-retail-k3` into `results/ollama-mistral-nemo.json`:

| Metric | Value |
| --- | ---: |
| pass@1 | 0.040 |
| bootstrap 95% CI | 0.000 – 0.120 |
| pass^2 | 0.040 |
| pass^3 | 0.040 |
| pass^5 | 0.000 (k was 3) |
| cost per success | $0.00 |
| ASR | not measured |
| tasks / trials | 25 / 75 |
| trials that returned a final answer | 6 |

Failure tags: gave_up 69, wrong_args 3. Most trials ended as error or timeout rather than a clean final answer.

## Still unanswered

- How fast pass@1 falls by pass^5 (needs k≥5).
- Whether attack success rises with model capability (ASR only measured for qwen).
- Which guardrail keeps the most utility for the least extra cost.
- Whether a small local model plus retries is cheaper per success than an API model (no Groq run).

Copy graded numbers into `results/<model>.json` only after a real command finishes. Do not fill the file in by hand.
