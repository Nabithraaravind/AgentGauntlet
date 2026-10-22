"""Dollar cost of a model call.

Example:
    from agentgauntlet.cost import usage_cost_usd

    usage_cost_usd("ollama/qwen2.5:7b-instruct", prompt_tokens=10, completion_tokens=2)
"""

from agentgauntlet.cost.tracker import gpu_cost_usd, token_cost_usd, usage_cost_usd

__all__ = ["gpu_cost_usd", "token_cost_usd", "usage_cost_usd"]
