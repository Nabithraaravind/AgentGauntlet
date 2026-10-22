"""The planned model list is data, not a measured score."""

from agentgauntlet.experiments import PLANNED_MODELS, model_status


def test_status_uses_the_caller_ping() -> None:
    """A model is ready only when the supplied ping says so."""
    assert len(PLANNED_MODELS) >= 4
    status = model_status(lambda name: name.endswith("3b"))
    ready = [name for name, ok in status if ok]
    assert ready == ["ollama/llama3.2:3b"]
    assert all(not ok for _name, ok in model_status(lambda _name: False))
