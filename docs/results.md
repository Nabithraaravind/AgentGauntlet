# Results

One measured retail run is recorded.

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

Failure tags across graded trials: gave_up 11, step_limit 9, policy_violation 8, wrong_args 6, tool_error_not_recovered 3, wrong_tool 3.

The injection table is in `results/ollama-qwen2.5-7b-instruct-asr.json`. Every cell is ASR 0.00 / utility 0.00: the model never produced an attacker database row, and it also failed the underlying lookup tasks in those trials.

## Still unanswered

The planned set also includes llama3.1:8b, mistral-nemo, phi3:mini, and llama3.2:3b through Ollama, plus Groq-hosted Llama 3.1 8B when `GROQ_API_KEY` is set. Those runs are not graded yet. Questions that still need more than one model:

- How fast pass@1 falls by pass^5 (needs k≥5).
- Which failure tags dominate for small and large models.
- Whether attack success rises with model capability.
- Which guardrail keeps the most utility for the least extra cost.
- Whether a small local model plus retries is cheaper per success than an API model.

Copy graded numbers into `results/<model>.json` only after a real command finishes. Do not fill the file in by hand.
