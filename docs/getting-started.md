# Getting started

Install from a checkout. The PyPI upload runs from the release workflow when a `v*` tag is pushed and trusted publishing is configured. After that tag publishes, install with `pip install agent-gauntlet` and import `agentgauntlet`.

```bash
uv sync
uv run gauntlet list tasks --domain retail
uv run gauntlet run --tasks retail-001 --k 1 --run-id smoke
uv run gauntlet report runs/smoke --html
uv run pytest
uv run python tasks/validate.py
```

`gauntlet run` uses the scripted agent unless you pass `--agent react`. A React run needs a model. A local Ollama model needs no API key:

```bash
uv run gauntlet run --agent react --model ollama/qwen2.5:7b-instruct --tasks retail --k 3 --run-id qwen --timeout 300
```

That command has not been recorded on this machine. Ollama is not installed here.
