# Results

Measured retail runs (k=3, 25 tasks, 75 trials) are recorded below. Numbers come only from finished local runs.

## Summary

| Model | pass@1 | pass^3 | ASR | Cost / success | Run |
| --- | ---: | ---: | ---: | ---: | --- |
| ollama/qwen2.5:7b-instruct | 0.467 | 0.400 | 0.000 | $0 | `qwen-retail-k3` |
| ollama/llama3.2:3b | 0.040 | 0.040 | — | $0 | `llama32-retail-k3` |

Not yet graded: `ollama/phi3:mini`, `ollama/llama3.1:8b`, `ollama/mistral-nemo`. `groq/llama-3.1-8b-instant` was not run because `GROQ_API_KEY` is unset.

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

## Still unanswered

- How fast pass@1 falls by pass^5 (needs k≥5).
- Whether attack success rises with model capability (ASR only measured for qwen).
- Which guardrail keeps the most utility for the least extra cost.
- Whether a small local model plus retries is cheaper per success than an API model (no Groq run).

Copy graded numbers into `results/<model>.json` only after a real command finishes. Do not fill the file in by hand.
