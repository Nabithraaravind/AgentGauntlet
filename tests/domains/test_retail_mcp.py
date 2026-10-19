"""Call every retail tool through an MCP client.

The client is opened inside the test. Yielding it from a fixture tears the
connection down on a different task, and anyio then raises a cancel-scope error.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

from agentgauntlet.domains.base import DomainError
from agentgauntlet.domains.retail import RetailDomain

TOOL_NAMES = (
    "cancel_order",
    "create_return",
    "get_order",
    "get_policy",
    "issue_refund",
    "list_orders",
    "search_products",
    "update_address",
)


@pytest.fixture
def retail(tmp_path: Path) -> RetailDomain:
    """A seeded shop, one per test, so writes do not leak."""
    domain = RetailDomain(tmp_path / "retail.sqlite", seed=17)
    domain.setup()
    return domain


def payload(result: object) -> dict[str, object]:
    """Return the structured tool body, which is the dict the tool returned."""
    assert getattr(result, "is_error", None) is False
    content = getattr(result, "structured_content", None)
    assert isinstance(content, dict)
    return content


def records(value: object) -> list[dict[str, object]]:
    """Narrow a tool field to a list of records."""
    assert isinstance(value, list)
    rows: list[dict[str, object]] = []
    for item in value:
        assert isinstance(item, dict)
        rows.append(item)
    return rows


def error_text(result: object) -> str:
    """Return the text of a failed tool call."""
    assert getattr(result, "is_error", None) is True
    block = result.content[0]  # type: ignore[attr-defined]
    assert isinstance(block, TextContent)
    return block.text


async def test_client_lists_every_tool(retail: RetailDomain) -> None:
    """The server publishes the eight retail tools and their argument schemas."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        assert tuple(sorted(by_name)) == TOOL_NAMES
        cancel = by_name["cancel_order"].input_schema
        assert cancel["properties"]["order_id"]["type"] == "string"
        assert "order_id" in cancel["required"]
        refund = by_name["issue_refund"].input_schema
        assert "amount_inr" in refund["required"]
        assert "method" in refund["required"]


async def test_search_and_get_order(retail: RetailDomain) -> None:
    """Search finds the headphones, and the order view includes both lines."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        found = payload(await client.call_tool("search_products", {"query": "headphones"}))
        assert [row["sku"] for row in records(found["products"])] == ["HP-220"]

        computers = payload(
            await client.call_tool("search_products", {"query": "", "category": "computers"})
        )
        assert {row["sku"] for row in records(computers["products"])} == {"KB-305", "MS-118"}

        order = payload(await client.call_tool("get_order", {"order_id": "A1043"}))
        assert {row["product_sku"] for row in records(order["items"])} == {"HP-220", "CH-110"}
        missing = error_text(await client.call_tool("get_order", {"order_id": "A0000"}))
        assert "not_found" in missing


async def test_list_orders_filters(retail: RetailDomain) -> None:
    """Filters narrow the order list to the customer and the status asked for."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        placed = payload(await client.call_tool("list_orders", {"status": "placed"}))
        assert "A1045" in {row["id"] for row in records(placed["orders"])}
        priya = payload(await client.call_tool("list_orders", {"customer_id": "C001"}))
        assert {"A1043", "A1046"} <= {row["id"] for row in records(priya["orders"])}


async def test_cancel_only_a_placed_order(retail: RetailDomain) -> None:
    """A placed order cancels and restocks. A shipped order does not."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        refused = error_text(await client.call_tool("cancel_order", {"order_id": "A1044"}))
        assert "cannot_cancel" in refused
        missing = error_text(await client.call_tool("cancel_order", {"order_id": "A0000"}))
        assert "not_found" in missing
        cancelled = payload(await client.call_tool("cancel_order", {"order_id": "A1045"}))
        assert cancelled["status"] == "cancelled"
        again = error_text(await client.call_tool("cancel_order", {"order_id": "A1045"}))
        assert "cannot_cancel" in again
        mouse = next(row for row in retail.snapshot()["products"] if row["sku"] == "MS-118")
        assert mouse["stock"] == 21


async def test_update_address_only_while_placed(retail: RetailDomain) -> None:
    """Address changes are refused once the order has shipped."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        moved = payload(
            await client.call_tool(
                "update_address",
                {"order_id": "A1045", "address": "9 MG Road", "city": "Pune"},
            )
        )
        assert moved["shipping_city"] == "Pune"
        order = next(row for row in retail.snapshot()["orders"] if row["id"] == "A1045")
        assert order["shipping_city"] == "Pune"
        refused = error_text(
            await client.call_tool(
                "update_address",
                {"order_id": "A1044", "address": "9 MG Road", "city": "Pune"},
            )
        )
        assert "cannot_update_address" in refused
        empty = error_text(
            await client.call_tool(
                "update_address",
                {"order_id": "A1045", "address": "   ", "city": "Pune"},
            )
        )
        assert "empty_field" in empty


async def test_partial_return_and_refund(retail: RetailDomain) -> None:
    """Returning only the headphones refunds that line and keeps the charger."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        created = payload(
            await client.call_tool(
                "create_return",
                {"order_id": "A1043", "product_sku": "HP-220", "reason": "Did not fit"},
            )
        )
        assert created["status"] == "requested"
        assert created["order_status"] == "partially_returned"
        refunded = payload(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1043", "amount_inr": 2499, "method": "original"},
            )
        )
        assert refunded["amount_inr"] == 2499
        too_much = error_text(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1043", "amount_inr": 1, "method": "original"},
            )
        )
        assert "amount_exceeds_returned" in too_much
        snapshot = retail.snapshot()
        order = next(row for row in snapshot["orders"] if row["id"] == "A1043")
        assert order["status"] == "partially_returned"
        assert snapshot["returns"] == [
            {
                "id": 1,
                "order_id": "A1043",
                "product_sku": "HP-220",
                "reason": "Did not fit",
                "requested_on": "2026-10-01",
                "status": "requested",
            }
        ]
        assert snapshot["refunds"][0]["amount_inr"] == 2499
        assert snapshot["refunds"][0]["method"] == "original"


async def test_full_return_marks_the_order_returned(retail: RetailDomain) -> None:
    """Returning the only line on an order closes it."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        created = payload(
            await client.call_tool(
                "create_return",
                {"order_id": "A1047", "product_sku": "BT-501", "reason": "Leaked"},
            )
        )
        assert created["order_status"] == "returned"
        refunded = payload(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1047", "amount_inr": 998, "method": "store_credit"},
            )
        )
        assert refunded["method"] == "store_credit"


async def test_return_rules(retail: RetailDomain) -> None:
    """Returns fail outside the window, on the wrong SKU, or twice."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        closed = error_text(
            await client.call_tool(
                "create_return",
                {"order_id": "A1046", "product_sku": "BK-014", "reason": "Too late"},
            )
        )
        assert "return_window_closed" in closed
        not_delivered = error_text(
            await client.call_tool(
                "create_return",
                {"order_id": "A1045", "product_sku": "MS-118", "reason": "Changed mind"},
            )
        )
        assert "not_delivered" in not_delivered
        wrong_sku = error_text(
            await client.call_tool(
                "create_return",
                {"order_id": "A1043", "product_sku": "BK-014", "reason": "Wrong item"},
            )
        )
        assert "sku_not_on_order" in wrong_sku
        payload(
            await client.call_tool(
                "create_return",
                {"order_id": "A1043", "product_sku": "HP-220", "reason": "Did not fit"},
            )
        )
        duplicate = error_text(
            await client.call_tool(
                "create_return",
                {"order_id": "A1043", "product_sku": "HP-220", "reason": "Again"},
            )
        )
        assert "return_exists" in duplicate
        with retail.connect() as conn:
            conn.execute("UPDATE orders SET delivered_on = NULL WHERE id = 'A1047'")
        missing_date = error_text(
            await client.call_tool(
                "create_return",
                {"order_id": "A1047", "product_sku": "BT-501", "reason": "No date"},
            )
        )
        assert "not_delivered" in missing_date


async def test_refund_rules(retail: RetailDomain) -> None:
    """Refunds require a return, a positive amount, and a known method."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        needs_return = error_text(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1047", "amount_inr": 100, "method": "original"},
            )
        )
        assert "return_required" in needs_return
        closed = error_text(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1046", "amount_inr": 100, "method": "original"},
            )
        )
        assert "refund_window_closed" in closed
        zero = error_text(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1047", "amount_inr": 0, "method": "original"},
            )
        )
        assert "invalid_amount" in zero
        with pytest.raises(DomainError, match="invalid_amount"):
            retail.issue_refund("A1047", True, "original")
        bad_method = error_text(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1047", "amount_inr": 100, "method": "upi"},
            )
        )
        assert "invalid_method" in bad_method


async def test_get_policy(retail: RetailDomain) -> None:
    """The policy tool returns the same SOP the server was given."""
    async with Client(retail.mcp_server(), raise_exceptions=True) as client:
        body = payload(await client.call_tool("get_policy", {}))
        policy = body["policy"]
        assert isinstance(policy, str)
        assert "30" in policy
        assert "original" in policy


async def test_flaky_mode_does_not_write(tmp_path: Path) -> None:
    """A flaky tool fails before the write, and the failure is retryable."""
    domain = RetailDomain(tmp_path / "retail.sqlite", seed=17, flaky_rate=1.0)
    domain.setup()
    before = domain.snapshot()
    seen: set[str] = set()
    async with Client(domain.mcp_server(), raise_exceptions=True) as client:
        for _ in range(16):
            result = await client.call_tool("cancel_order", {"order_id": "A1045"})
            text = error_text(result)
            assert "retryable" in text
            seen.add(text.split(":", maxsplit=2)[1].strip())
    assert {"timeout", "internal"} <= seen
    assert domain.snapshot() == before


async def test_stdio_client_calls_every_tool(tmp_path: Path) -> None:
    """A real stdio subprocess exposes the same tools and applies a write."""
    db = tmp_path / "retail.sqlite"
    RetailDomain(db, seed=17).setup()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentgauntlet.domains.retail", "--db", str(db), "--seed", "17"],
    )
    async with Client(params) as client:
        listed = await client.list_tools()
        assert tuple(sorted(tool.name for tool in listed.tools)) == TOOL_NAMES
        found = payload(await client.call_tool("search_products", {"query": "headphones"}))
        assert records(found["products"])[0]["sku"] == "HP-220"
        policy = payload(await client.call_tool("get_policy", {}))
        assert "2026-10-01" in str(policy["policy"])
        order = payload(await client.call_tool("get_order", {"order_id": "A1043"}))
        assert isinstance(order["order"], dict)
        assert order["order"]["id"] == "A1043"
        listed_orders = payload(await client.call_tool("list_orders", {"status": "placed"}))
        assert "A1045" in {row["id"] for row in records(listed_orders["orders"])}
        moved = payload(
            await client.call_tool(
                "update_address",
                {"order_id": "A1045", "address": "9 MG Road", "city": "Pune"},
            )
        )
        assert moved["shipping_city"] == "Pune"
        created = payload(
            await client.call_tool(
                "create_return",
                {"order_id": "A1043", "product_sku": "HP-220", "reason": "Did not fit"},
            )
        )
        assert created["order_status"] == "partially_returned"
        refunded = payload(
            await client.call_tool(
                "issue_refund",
                {"order_id": "A1043", "amount_inr": 2499, "method": "original"},
            )
        )
        assert refunded["status"] == "issued"
        cancelled = payload(await client.call_tool("cancel_order", {"order_id": "A1045"}))
        assert cancelled["status"] == "cancelled"

    snapshot = RetailDomain(db, seed=17).snapshot()
    headphones = next(row for row in snapshot["returns"] if row["product_sku"] == "HP-220")
    assert headphones["status"] == "requested"
    assert snapshot["refunds"][0]["amount_inr"] == 2499
