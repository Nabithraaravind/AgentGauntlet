"""The model list for a measured run.

Nothing in this module calls a model. A caller supplies ``ping``. The results
write-up stays empty until a ping succeeds and a run is recorded.

Example:
    from agentgauntlet.experiments import PLANNED_MODELS, model_status

    model_status(lambda _name: False)
"""

from __future__ import annotations

from collections.abc import Callable

PLANNED_MODELS: tuple[str, ...] = (
    "ollama/qwen2.5:7b-instruct",
    "ollama/llama3.1:8b",
    "ollama/mistral-nemo",
    "ollama/phi3:mini",
    "ollama/llama3.2:3b",
    "groq/llama-3.1-8b-instant",
)


def model_status(ping: Callable[[str], bool]) -> list[tuple[str, bool]]:
    """Return each planned model and whether ``ping`` says it can be called."""
    return [(name, ping(name)) for name in PLANNED_MODELS]
