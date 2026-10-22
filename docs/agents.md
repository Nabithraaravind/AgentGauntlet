# Agents

An agent has a `name` and an async `act(task, history, tools)` method. It returns one tool call or a final answer. The runner performs the tool call.

`ScriptedAgent` plays the reference solution and ignores tool text. Tests and CI use it.

`ReactAgent` sends one LiteLLM request per step. Pass a `complete` function in tests so the suite never calls a model.
