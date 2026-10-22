"""Hand-checked prices. Ollama is free. GPU time is a separate rate."""

import pytest

from agentgauntlet.cost import gpu_cost_usd, token_cost_usd, usage_cost_usd


def test_ollama_tokens_are_free_and_gpu_time_is_priced_by_hand() -> None:
    """1_800_000 ms is half an hour. At $2 per hour that is $1, on top of $0 tokens."""
    assert token_cost_usd("ollama/qwen2.5:7b-instruct", 100, 20) == 0
    assert token_cost_usd("ollama_chat/llama3.1:8b", 1, 1) == 0
    assert gpu_cost_usd(1_800_000, 2) == 1
    assert (
        usage_cost_usd(
            "ollama/qwen2.5:7b-instruct",
            100,
            20,
            latency_ms=1_800_000,
            gpu_usd_per_hour=2,
        )
        == 1
    )


def test_a_priced_model_uses_litellm_and_a_failure_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tracker asks LiteLLM. A missing price, or a non-numeric one, stays zero."""
    import litellm

    def priced(**_kwargs: object) -> float:
        return 0.02

    monkeypatch.setattr(litellm, "completion_cost", priced)
    assert token_cost_usd("gpt-4o-mini", 10, 2) == 0.02

    def broken(**_kwargs: object) -> float:
        raise RuntimeError("no price")

    monkeypatch.setattr(litellm, "completion_cost", broken)
    assert token_cost_usd("gpt-4o-mini", 10, 2) == 0

    def odd(**_kwargs: object) -> str:
        return "nope"

    monkeypatch.setattr(litellm, "completion_cost", odd)
    assert token_cost_usd("gpt-4o-mini", 10, 2) == 0


def test_negative_counts_and_rates_are_rejected() -> None:
    """A negative token count or GPU rate is a caller bug."""
    with pytest.raises(ValueError, match="token counts"):
        token_cost_usd("ollama/qwen2.5:7b-instruct", -1, 0)
    with pytest.raises(ValueError, match="GPU"):
        gpu_cost_usd(-1, 0)
    with pytest.raises(ValueError, match="GPU"):
        gpu_cost_usd(0, -1)
