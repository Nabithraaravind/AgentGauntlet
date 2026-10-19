"""Retail world: orders, returns, and refunds.

Tools enforce the support policy in ``policy.md``. A write that breaks a rule
raises ``DomainError``; the MCP layer turns that into a tool error the agent
can read.

Example:
    from pathlib import Path

    from agentgauntlet.domains.retail import RetailDomain

    world = RetailDomain(Path("retail.sqlite"), seed=17)
    world.setup()
    world.mcp_server()
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta
from importlib.resources import files
from typing import cast

from faker import Faker
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from agentgauntlet.domains.base import Domain, DomainError
from agentgauntlet.domains.retail.catalog import (
    CLOCK,
    CUSTOMERS,
    ORDERS,
    PRODUCTS,
    REFUND_WINDOW_DAYS,
    Customer,
    Order,
    Product,
)

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

_SCHEMA = """
CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    city TEXT NOT NULL,
    address TEXT NOT NULL
);

CREATE TABLE products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_inr INTEGER NOT NULL CHECK (price_inr > 0),
    stock INTEGER NOT NULL CHECK (stock >= 0)
);

CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL CHECK (
        status IN (
            'placed', 'shipped', 'delivered', 'cancelled', 'partially_returned', 'returned'
        )
    ),
    payment_method TEXT NOT NULL CHECK (payment_method IN ('upi', 'card', 'cod')),
    shipping_address TEXT NOT NULL,
    shipping_city TEXT NOT NULL,
    ordered_on TEXT NOT NULL,
    delivered_on TEXT
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_sku TEXT NOT NULL REFERENCES products(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_inr INTEGER NOT NULL CHECK (unit_price_inr > 0),
    UNIQUE (order_id, product_sku)
);

CREATE TABLE returns (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_sku TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('requested', 'approved', 'rejected', 'received')),
    reason TEXT NOT NULL,
    requested_on TEXT NOT NULL,
    UNIQUE (order_id, product_sku)
);

CREATE TABLE refunds (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    amount_inr INTEGER NOT NULL CHECK (amount_inr > 0),
    method TEXT NOT NULL CHECK (method IN ('original', 'store_credit')),
    status TEXT NOT NULL CHECK (status IN ('issued', 'failed')),
    issued_on TEXT NOT NULL
);
"""

_REFUND_METHODS = frozenset({"original", "store_credit"})
_EXTRA_CUSTOMERS = 4
_EXTRA_ORDER_STATUSES = ("placed", "shipped", "delivered")


class RetailDomain(Domain):
    """A shop database and the eight tools a support agent can call."""

    name = "retail"
    clock = CLOCK
    refund_window_days = REFUND_WINDOW_DAYS

    def schema(self) -> str:
        """Return the retail ``CREATE TABLE`` script."""
        return _SCHEMA

    def policy(self) -> str:
        """Return the customer-support SOP."""
        return (
            files("agentgauntlet.domains.retail").joinpath("policy.md").read_text(encoding="utf-8")
        )

    def seed(self, rng: random.Random) -> None:
        """Insert the fixed spine, then a few Faker customers and orders."""
        with self.connect() as conn:
            for product in PRODUCTS:
                _insert_product(conn, product)
            for customer in CUSTOMERS:
                _insert_customer(conn, customer)
            customers_by_id = {customer.id: customer for customer in CUSTOMERS}
            for order in ORDERS:
                _insert_order(conn, order, customers_by_id[order.customer_id])
            _seed_extras(conn, rng, self.clock)

    def search_products(self, query: str, category: str | None = None) -> dict[str, object]:
        """Find products whose name or SKU contains ``query``.

        An empty query matches every product. ``category`` is an exact match.
        """
        self.raise_if_flaky()
        needle = query.casefold()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT sku, name, category, price_inr, stock FROM products ORDER BY sku"
            ).fetchall()
        products = [
            _record(row)
            for row in rows
            if needle in str(row["name"]).casefold() or needle in str(row["sku"]).casefold()
            if category is None or row["category"] == category
        ]
        return {"ok": True, "products": products}

    def get_order(self, order_id: str) -> dict[str, object]:
        """Return one order with its line items, returns, and refunds."""
        self.raise_if_flaky()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT o.*, c.name AS customer_name, c.email AS customer_email
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.id = ?
                """,
                (order_id,),
            ).fetchone()
            if row is None:
                raise DomainError("not_found", f"No order with id {order_id}.")
            items = conn.execute(
                """
                SELECT product_sku, quantity, unit_price_inr
                FROM order_items WHERE order_id = ? ORDER BY product_sku
                """,
                (order_id,),
            ).fetchall()
            returns = conn.execute(
                """
                SELECT product_sku, status, reason, requested_on
                FROM returns WHERE order_id = ? ORDER BY product_sku
                """,
                (order_id,),
            ).fetchall()
            refunds = conn.execute(
                """
                SELECT amount_inr, method, status, issued_on
                FROM refunds WHERE order_id = ? ORDER BY id
                """,
                (order_id,),
            ).fetchall()
        return {
            "ok": True,
            "order": _record(row),
            "items": [_record(item) for item in items],
            "returns": [_record(item) for item in returns],
            "refunds": [_record(item) for item in refunds],
        }

    def list_orders(
        self, customer_id: str | None = None, status: str | None = None
    ) -> dict[str, object]:
        """List orders, optionally filtered by customer and status."""
        self.raise_if_flaky()
        clauses: list[str] = []
        params: list[object] = []
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM orders {where} ORDER BY id",  # noqa: S608
                params,
            ).fetchall()
        return {"ok": True, "orders": [_record(row) for row in rows]}

    def cancel_order(self, order_id: str) -> dict[str, object]:
        """Cancel a placed order and put its units back in stock."""
        self.raise_if_flaky()
        with self.connect() as conn:
            order = _require_order(conn, order_id)
            if order["status"] != "placed":
                raise DomainError(
                    "cannot_cancel",
                    f"Order {order_id} is {order['status']} and cannot be cancelled.",
                )
            conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            for item in conn.execute(
                "SELECT product_sku, quantity FROM order_items WHERE order_id = ?",
                (order_id,),
            ):
                conn.execute(
                    "UPDATE products SET stock = stock + ? WHERE sku = ?",
                    (item["quantity"], item["product_sku"]),
                )
        return {"ok": True, "order_id": order_id, "status": "cancelled"}

    def update_address(self, order_id: str, address: str, city: str) -> dict[str, object]:
        """Change the shipping address of an order that has not shipped."""
        self.raise_if_flaky()
        _require_text(address, "address")
        _require_text(city, "city")
        with self.connect() as conn:
            order = _require_order(conn, order_id)
            if order["status"] != "placed":
                raise DomainError(
                    "cannot_update_address",
                    f"Order {order_id} is {order['status']}. "
                    "The address can only change while it is placed.",
                )
            conn.execute(
                "UPDATE orders SET shipping_address = ?, shipping_city = ? WHERE id = ?",
                (address.strip(), city.strip(), order_id),
            )
        return {
            "ok": True,
            "order_id": order_id,
            "shipping_address": address.strip(),
            "shipping_city": city.strip(),
        }

    def create_return(self, order_id: str, product_sku: str, reason: str) -> dict[str, object]:
        """Request a return for one SKU line on a delivered order."""
        self.raise_if_flaky()
        _require_text(reason, "reason")
        with self.connect() as conn:
            order = _require_order(conn, order_id)
            _require_in_window(order, self.clock, self.refund_window_days, "return_window_closed")
            item = conn.execute(
                """
                SELECT quantity, unit_price_inr FROM order_items
                WHERE order_id = ? AND product_sku = ?
                """,
                (order_id, product_sku),
            ).fetchone()
            if item is None:
                raise DomainError(
                    "sku_not_on_order",
                    f"Order {order_id} does not contain SKU {product_sku}.",
                )
            existing = conn.execute(
                "SELECT id FROM returns WHERE order_id = ? AND product_sku = ?",
                (order_id, product_sku),
            ).fetchone()
            if existing is not None:
                raise DomainError(
                    "return_exists",
                    f"SKU {product_sku} on order {order_id} already has a return.",
                )
            requested_on = self.clock.isoformat()
            conn.execute(
                """
                INSERT INTO returns (order_id, product_sku, status, reason, requested_on)
                VALUES (?, ?, 'requested', ?, ?)
                """,
                (order_id, product_sku, reason.strip(), requested_on),
            )
            status = _return_status(conn, order_id)
            conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        return {
            "ok": True,
            "order_id": order_id,
            "product_sku": product_sku,
            "status": "requested",
            "order_status": status,
        }

    def issue_refund(self, order_id: str, amount_inr: int, method: str) -> dict[str, object]:
        """Refund up to the value of the returned lines."""
        self.raise_if_flaky()
        if type(amount_inr) is not int or amount_inr <= 0:
            raise DomainError(
                "invalid_amount", "Refund amount must be a positive number of rupees."
            )
        if method not in _REFUND_METHODS:
            raise DomainError(
                "invalid_method",
                "Refund method must be 'original' or 'store_credit'.",
            )
        with self.connect() as conn:
            order = _require_order(conn, order_id)
            _require_in_window(order, self.clock, self.refund_window_days, "refund_window_closed")
            returned = conn.execute(
                """
                SELECT COALESCE(SUM(i.quantity * i.unit_price_inr), 0) AS total
                FROM returns r
                JOIN order_items i
                  ON i.order_id = r.order_id AND i.product_sku = r.product_sku
                WHERE r.order_id = ? AND r.status != 'rejected'
                """,
                (order_id,),
            ).fetchone()
            returned_total = int(returned["total"]) if returned is not None else 0
            if returned_total <= 0:
                raise DomainError(
                    "return_required",
                    f"Order {order_id} has no return to refund. Create the return first.",
                )
            already = conn.execute(
                "SELECT COALESCE(SUM(amount_inr), 0) AS total FROM refunds WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            already_total = int(already["total"]) if already is not None else 0
            remaining = returned_total - already_total
            if amount_inr > remaining:
                raise DomainError(
                    "amount_exceeds_returned",
                    f"Refund of {amount_inr} INR exceeds the {remaining} INR "
                    f"still refundable on {order_id}.",
                )
            issued_on = self.clock.isoformat()
            conn.execute(
                """
                INSERT INTO refunds (order_id, amount_inr, method, status, issued_on)
                VALUES (?, ?, ?, 'issued', ?)
                """,
                (order_id, amount_inr, method, issued_on),
            )
        return {
            "ok": True,
            "order_id": order_id,
            "amount_inr": amount_inr,
            "method": method,
            "status": "issued",
        }

    def get_policy(self) -> dict[str, object]:
        """Return the support policy the agent should follow."""
        self.raise_if_flaky()
        return {"ok": True, "policy": self.policy()}

    def mcp_server(self) -> MCPServer[None]:
        """Build an MCP server that calls this domain's tools."""
        server: MCPServer[None] = MCPServer("retail", instructions=self.policy())
        domain = self

        def run(body: Callable[[], dict[str, object]]) -> dict[str, object]:
            try:
                return body()
            except DomainError as exc:
                raise ToolError(str(exc)) from exc

        @server.tool(annotations=_READ)
        def search_products(query: str, category: str | None = None) -> dict[str, object]:
            """Search products by name or SKU. Category is an optional exact match."""
            return run(lambda: domain.search_products(query, category))

        @server.tool(annotations=_READ)
        def get_order(order_id: str) -> dict[str, object]:
            """Fetch one order, including items, returns, and refunds."""
            return run(lambda: domain.get_order(order_id))

        @server.tool(annotations=_READ)
        def list_orders(
            customer_id: str | None = None, status: str | None = None
        ) -> dict[str, object]:
            """List orders. Filter by customer id, status, or both."""
            return run(lambda: domain.list_orders(customer_id, status))

        @server.tool(annotations=_DESTRUCTIVE)
        def cancel_order(order_id: str) -> dict[str, object]:
            """Cancel an order that is still placed."""
            return run(lambda: domain.cancel_order(order_id))

        @server.tool(annotations=_WRITE)
        def create_return(order_id: str, product_sku: str, reason: str) -> dict[str, object]:
            """Request a return for one SKU on a delivered order."""
            return run(lambda: domain.create_return(order_id, product_sku, reason))

        @server.tool(annotations=_DESTRUCTIVE)
        def issue_refund(order_id: str, amount_inr: int, method: str) -> dict[str, object]:
            """Refund a returned order to the original payment method or store credit."""
            return run(lambda: domain.issue_refund(order_id, amount_inr, method))

        @server.tool(annotations=_WRITE)
        def update_address(order_id: str, address: str, city: str) -> dict[str, object]:
            """Change the shipping address of an order that has not shipped."""
            return run(lambda: domain.update_address(order_id, address, city))

        @server.tool(annotations=_READ)
        def get_policy() -> dict[str, object]:
            """Read the retail support policy."""
            return run(domain.get_policy)

        return server


def _record(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in sorted(row.keys())}


def _require_text(value: str, field: str) -> None:
    if value.strip() == "":
        raise DomainError("empty_field", f"{field} must not be empty.")


def _require_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise DomainError("not_found", f"No order with id {order_id}.")
    return cast(sqlite3.Row, row)


def _require_in_window(order: sqlite3.Row, today: date, window_days: int, code: str) -> None:
    if order["status"] not in {"delivered", "partially_returned", "returned"}:
        raise DomainError(
            "not_delivered",
            f"Order {order['id']} is {order['status']} and has not been delivered.",
        )
    delivered_on = order["delivered_on"]
    if not isinstance(delivered_on, str):
        raise DomainError("not_delivered", f"Order {order['id']} has no delivery date.")
    age = (today - date.fromisoformat(delivered_on)).days
    if age > window_days:
        raise DomainError(
            code,
            f"Order {order['id']} was delivered on {delivered_on}, "
            f"which is outside the {window_days}-day window.",
        )


def _return_status(conn: sqlite3.Connection, order_id: str) -> str:
    items = conn.execute(
        "SELECT COUNT(*) AS total FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    returned = conn.execute(
        "SELECT COUNT(*) AS total FROM returns WHERE order_id = ? AND status != 'rejected'",
        (order_id,),
    ).fetchone()
    item_count = int(items["total"]) if items is not None else 0
    return_count = int(returned["total"]) if returned is not None else 0
    if return_count >= item_count:
        return "returned"
    return "partially_returned"


def _insert_product(conn: sqlite3.Connection, product: Product) -> None:
    conn.execute(
        "INSERT INTO products (sku, name, category, price_inr, stock) VALUES (?, ?, ?, ?, ?)",
        (product.sku, product.name, product.category, product.price_inr, product.stock),
    )


def _insert_customer(conn: sqlite3.Connection, customer: Customer) -> None:
    conn.execute(
        """
        INSERT INTO customers (id, name, email, phone, city, address)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            customer.id,
            customer.name,
            customer.email,
            customer.phone,
            customer.city,
            customer.address,
        ),
    )


def _insert_order(conn: sqlite3.Connection, order: Order, customer: Customer) -> None:
    conn.execute(
        """
        INSERT INTO orders (
            id, customer_id, status, payment_method, shipping_address,
            shipping_city, ordered_on, delivered_on
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order.id,
            order.customer_id,
            order.status,
            order.payment_method,
            customer.address,
            customer.city,
            order.ordered_on,
            order.delivered_on,
        ),
    )
    prices = {product.sku: product.price_inr for product in PRODUCTS}
    for item in order.items:
        conn.execute(
            """
            INSERT INTO order_items (order_id, product_sku, quantity, unit_price_inr)
            VALUES (?, ?, ?, ?)
            """,
            (order.id, item.sku, item.quantity, prices[item.sku]),
        )


def _seed_extras(conn: sqlite3.Connection, rng: random.Random, today: date) -> None:
    """Add customers and orders that vary with the seed.

    The statuses are fixed (one placed, one shipped, one delivered) so every
    seed still contains those cases. Names, cities, and which SKU was bought
    come from the seeded RNG and from Faker's ``en_IN`` locale.
    """
    fake = Faker("en_IN")
    fake.seed_instance(rng.randrange(1, 2**31 - 1))
    extra_ids: list[str] = []
    for offset in range(_EXTRA_CUSTOMERS):
        customer_id = f"C{101 + offset}"
        extra_ids.append(customer_id)
        conn.execute(
            """
            INSERT INTO customers (id, name, email, phone, city, address)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                fake.name(),
                fake.email(),
                fake.phone_number(),
                fake.city(),
                fake.street_address(),
            ),
        )
    skus = [product.sku for product in PRODUCTS]
    prices = {product.sku: product.price_inr for product in PRODUCTS}
    for offset, status in enumerate(_EXTRA_ORDER_STATUSES):
        sku = skus[rng.randrange(len(skus))]
        delivered_on = (today - timedelta(days=5)).isoformat() if status == "delivered" else None
        order_id = f"A{2001 + offset}"
        conn.execute(
            """
            INSERT INTO orders (
                id, customer_id, status, payment_method, shipping_address,
                shipping_city, ordered_on, delivered_on
            ) VALUES (?, ?, ?, 'upi', ?, ?, ?, ?)
            """,
            (
                order_id,
                extra_ids[rng.randrange(len(extra_ids))],
                status,
                fake.street_address(),
                fake.city(),
                (today - timedelta(days=10)).isoformat(),
                delivered_on,
            ),
        )
        conn.execute(
            """
            INSERT INTO order_items (order_id, product_sku, quantity, unit_price_inr)
            VALUES (?, ?, 1, ?)
            """,
            (order_id, sku, prices[sku]),
        )
