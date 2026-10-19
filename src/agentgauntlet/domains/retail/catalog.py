"""Fixed retail catalog and the orders every seed contains.

Tasks name these ids (``A1043``, ``HP-220``, and so on). Faker may add more
customers and orders around them, but it must not change this spine.
Money is an integer number of rupees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# The benchmark clock does not follow the wall clock. "Within 30 days" stays
# true for the same rows next year.
CLOCK = date(2026, 10, 1)
REFUND_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Product:
    """One catalog SKU."""

    sku: str
    name: str
    category: str
    price_inr: int
    stock: int


@dataclass(frozen=True)
class Customer:
    """A shopper that exists in every seed."""

    id: str
    name: str
    email: str
    phone: str
    city: str
    address: str


@dataclass(frozen=True)
class LineItem:
    """Units of one SKU on an order."""

    sku: str
    quantity: int


@dataclass(frozen=True)
class Order:
    """An order that exists in every seed."""

    id: str
    customer_id: str
    status: str
    payment_method: str
    ordered_on: str
    delivered_on: str | None
    items: tuple[LineItem, ...]


PRODUCTS: tuple[Product, ...] = (
    Product("BK-014", "Cotton Kurta", "apparel", 1299, 20),
    Product("BT-501", "Steel Water Bottle", "home", 499, 20),
    Product("CH-110", "USB-C Charger", "accessories", 799, 20),
    Product("HP-220", "Wireless Headphones", "audio", 2499, 20),
    Product("KB-305", "Mechanical Keyboard", "computers", 3499, 20),
    Product("MS-118", "Wireless Mouse", "computers", 899, 20),
)

CUSTOMERS: tuple[Customer, ...] = (
    Customer(
        "C001",
        "Priya Sharma",
        "priya.sharma@example.com",
        "+91-98450-10001",
        "Bengaluru",
        "12 Residency Road",
    ),
    Customer(
        "C002",
        "Arjun Mehta",
        "arjun.mehta@example.com",
        "+91-98200-10002",
        "Mumbai",
        "88 Linking Road",
    ),
    Customer(
        "C003",
        "Ananya Iyer",
        "ananya.iyer@example.com",
        "+91-94440-10003",
        "Chennai",
        "4 Cathedral Road",
    ),
)

# A1043 is the partial-return case: headphones and a charger, delivered a week ago.
# A1044 has shipped, so it cannot be cancelled. A1045 is still placed.
# A1046 was delivered 45 days ago, so the refund window is closed.
# A1047 is a single line that can be returned in full.
ORDERS: tuple[Order, ...] = (
    Order(
        "A1043",
        "C001",
        "delivered",
        "upi",
        "2026-09-20",
        "2026-09-24",
        (LineItem("HP-220", 1), LineItem("CH-110", 1)),
    ),
    Order(
        "A1044",
        "C002",
        "shipped",
        "card",
        "2026-09-28",
        None,
        (LineItem("KB-305", 1),),
    ),
    Order(
        "A1045",
        "C003",
        "placed",
        "cod",
        "2026-09-30",
        None,
        (LineItem("MS-118", 1),),
    ),
    Order(
        "A1046",
        "C001",
        "delivered",
        "upi",
        "2026-08-10",
        "2026-08-17",
        (LineItem("BK-014", 1),),
    ),
    Order(
        "A1047",
        "C002",
        "delivered",
        "card",
        "2026-09-15",
        "2026-09-20",
        (LineItem("BT-501", 2),),
    ),
)
