# Examples

## Run one task

```bash
uv run gauntlet run --tasks retail-001 --k 1 --run-id smoke
uv run gauntlet report runs/smoke --html
```

## A gate file

`gauntlet init gauntlet.yaml` writes:

```yaml
tasks:
  - retail-001
k: 1
thresholds:
  pass_at_1: 1.0
  pass_hat_k:
    k: 1
    min: 1.0
  cost_per_task_max_usd: 0.02
attacks: false
guardrail: none
```

`pytest --gauntlet --gauntlet-config gauntlet.yaml` fails the process when a limit is missed.

## A custom agent

An agent is any object with a `name` and an async `act(task, history, tools)` method that returns an `Action`. The scripted agent is the one CI runs. A model agent is `ReactAgent`.

```python
from agentgauntlet.agents import ReactAgent

agent = ReactAgent("ollama/qwen2.5:7b-instruct")
```

## A custom task

Tasks are YAML files in `src/agentgauntlet/tasks/library`. `tasks/validate.py` replays `reference_solution` and checks `expected_state`. Copy `retail-001.yaml` and keep the id pattern `name-001`.
