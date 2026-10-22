# Results

No model run is recorded.

The planned set is qwen2.5:7b-instruct, llama3.1:8b, mistral-nemo, phi3:mini, and llama3.2:3b through Ollama, plus Groq-hosted Llama 3.1 8B when `GROQ_API_KEY` is set. On this machine `ollama` is not on `PATH`, and no API key is stored in the repo. The questions below are therefore unanswered:

- How fast pass@1 falls by pass^5.
- Which failure tags dominate for small and large models.
- Whether attack success rises with model capability.
- Which guardrail keeps the most utility for the least extra cost.
- Whether a small local model plus retries is cheaper per success than an API model.

When a model can be called, the command is:

```bash
uv run gauntlet run --agent react --model ollama/qwen2.5:7b-instruct --tasks retail --k 3 --run-id qwen-retail --timeout 300
```

Copy the graded numbers into `results/<model>.json` only after that command finishes. Do not fill the file in by hand.
