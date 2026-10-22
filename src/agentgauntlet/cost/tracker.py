"""Turn token counts into a dollar cost.

Ollama models are priced at zero. An optional GPU rate can be added from the
wall time of the model call. A model LiteLLM cannot price is also recorded as
zero, so a missing price list does not fail the trial.

Example:
    from agentgauntlet.cost import usage_cost_usd

    usage_cost_usd(
        "ollama/qwen2.5:7b-instruct",
        prompt_tokens=100,
        completion_tokens=20,
        latency_ms=1_800_000,
        gpu_usd_per_hour=2,
    )
"""

from __future__ import annotations


def token_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return LiteLLM's dollar price for these tokens.

    Local Ollama model names are zero. A lookup that fails is also zero.
    """
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ValueError("token counts must be zero or more")
    if model.startswith(("ollama/", "ollama_chat/")):
        return 0.0
    try:
        import litellm

        priced: object = litellm.completion_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception:
        return 0.0
    if isinstance(priced, int | float):
        return float(priced)
    return 0.0


def gpu_cost_usd(latency_ms: float, usd_per_hour: float) -> float:
    """Return ``latency_ms / 3_600_000 * usd_per_hour``.

    ``1_800_000`` milliseconds at ``$2`` per hour is ``$1``.
    """
    if latency_ms < 0 or usd_per_hour < 0:
        raise ValueError("latency and GPU price must be zero or more")
    return latency_ms / 3_600_000 * usd_per_hour


def usage_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    latency_ms: float = 0,
    gpu_usd_per_hour: float = 0,
) -> float:
    """Return the token price plus the optional GPU price."""
    return token_cost_usd(model, prompt_tokens, completion_tokens) + gpu_cost_usd(
        latency_ms, gpu_usd_per_hour
    )
