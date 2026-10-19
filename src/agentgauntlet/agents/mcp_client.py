"""Call MCP tools and record how long they took.

The runner passes the in-memory ``mcp.Client``. A retry happens only when the
tool text says the error is retryable, and only ``retries`` extra times.

Example:
    from mcp import Client

    from agentgauntlet.agents.mcp_client import ToolSession
    from agentgauntlet.domains import RetailDomain

    world = RetailDomain(path, seed=17)
    world.setup()
    async with Client(world.mcp_server()) as client:
        session = ToolSession(client)
        outcome = await session.call("get_order", {"order_id": "A1043"})
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from mcp import Client
from mcp.types import CallToolResult, TextContent

from agentgauntlet.tasks.schema import JsonScalar

_RETRYABLE = "This error is retryable."


@dataclass(frozen=True)
class ToolOutcome:
    """What one tool call, including retries, returned."""

    tool: str
    arguments: dict[str, JsonScalar]
    text: str
    is_error: bool
    retryable: bool
    attempts: int
    latency_ms: float


class ToolSession:
    """List and call tools on an open MCP client."""

    def __init__(self, client: Client, *, retries: int = 0) -> None:
        """Bind a client. ``retries`` is the number of extra attempts after a retryable error."""
        if retries < 0:
            raise ValueError("retries must be zero or more")
        self._client = client
        self._retries = retries

    async def list_tools(self) -> list[str]:
        """Return the tool names the server advertised."""
        listed = await self._client.list_tools()
        return [tool.name for tool in listed.tools]

    async def call(self, tool: str, arguments: dict[str, JsonScalar]) -> ToolOutcome:
        """Call ``tool``. Retry while the error says it is retryable."""
        attempt = 0
        latency_ms = 0.0
        while True:
            attempt += 1
            started = time.perf_counter()
            result = await self._client.call_tool(tool, dict(arguments))
            latency_ms += (time.perf_counter() - started) * 1000
            text = message_text(result)
            retryable = bool(result.is_error) and _RETRYABLE in text
            if retryable and attempt <= self._retries:
                continue
            return ToolOutcome(
                tool=tool,
                arguments=dict(arguments),
                text=text,
                is_error=bool(result.is_error),
                retryable=retryable,
                attempts=attempt,
                latency_ms=latency_ms,
            )


def message_text(result: CallToolResult) -> str:
    """Return the first text block of a tool result, or an empty string."""
    if not result.content:
        return ""
    block = result.content[0]
    if isinstance(block, TextContent):
        return block.text
    return ""
