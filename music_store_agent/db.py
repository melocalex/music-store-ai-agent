"""Load the store CSVs into SQLite once, then read with bounded queries."""

import csv
import os
import sqlite3
from datetime import date
from pathlib import Path

from music_store_agent.constants import CATALOG_FETCH_LIMIT, ORDER_ITEMS_LIMIT

DATA_ENV = "MUSIC_STORE_DATA"

_SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    price_brl TEXT NOT NULL,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    stock_quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    specs TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_brl TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    tracking_code TEXT,
    estimated_delivery TEXT,
    notes TEXT NOT NULL
);
CREATE TABLE order_items (
    order_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    product_id INTEGER NOT NULL
);
CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    discount_percent TEXT NOT NULL,
    description TEXT NOT NULL,
    is_active INTEGER NOT NULL
);
"""


def data_dir() -> Path:
    override = os.environ.get(DATA_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data"


def load_database(folder: Path | None = None) -> sqlite3.Connection:
    root = folder or data_dir()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _load_all(conn, root)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _load_all(conn: sqlite3.Connection, root: Path) -> None:
    with conn:
        _load(conn, root / "categories.csv", "categories", _category)
        _load(conn, root / "products.csv", "products", _product)
        _load(conn, root / "customers.csv", "customers", _customer)
        _load(conn, root / "orders.csv", "orders", _order)
        _load(conn, root / "order_items.csv", "order_items", _item)
        _load(conn, root / "promotions.csv", "promotions", _promo)


def _load(conn: sqlite3.Connection, path: Path, table: str, mapper) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [mapper(row) for row in csv.DictReader(handle)]
    if not rows:
        return
    columns = ", ".join(rows[0].keys())
    marks = ", ".join("?" for _ in rows[0])
    conn.executemany(
        f"INSERT INTO {table} ({columns}) VALUES ({marks})", [tuple(r.values()) for r in rows]
    )


def _category(row: dict[str, str]) -> dict[str, object]:
    return {
        "category_id": int(row["category_id"]),
        "name": row["name"],
        "description": row["description"],
    }


def _product(row: dict[str, str]) -> dict[str, object]:
    return {
        "product_id": int(row["product_id"]),
        "price_brl": row["price_brl"],
        "name": row["name"],
        "category_id": int(row["category_id"]),
        "description": row["description"],
        "stock_quantity": int(row["stock_quantity"]),
        "status": row["status"],
        "specs": row["specs"],
        "created_at": row["created_at"],
    }


def _customer(row: dict[str, str]) -> dict[str, object]:
    return {
        "customer_id": int(row["customer_id"]),
        "name": row["name"],
        "phone": row["phone"],
        "email": row["email"],
        "city": row["city"],
    }


def _order(row: dict[str, str]) -> dict[str, object]:
    return {
        "order_id": int(row["order_id"]),
        "customer_id": int(row["customer_id"]),
        "order_date": row["order_date"],
        "status": row["status"],
        "total_brl": row["total_brl"],
        "payment_method": row["payment_method"],
        "tracking_code": row["tracking_code"] or None,
        "estimated_delivery": row["estimated_delivery"] or None,
        "notes": row["notes"],
    }


def _item(row: dict[str, str]) -> dict[str, object]:
    return {
        "order_id": int(row["order_id"]),
        "quantity": int(row["quantity"]),
        "product_id": int(row["product_id"]),
    }


def _promo(row: dict[str, str]) -> dict[str, object]:
    return {
        "promotion_id": int(row["promotion_id"]),
        "product_id": int(row["product_id"]),
        "discount_percent": row["discount_percent"],
        "description": row["description"],
        "is_active": int(row["is_active"]),
    }


def fetch_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    sql = """
        SELECT p.product_id, p.price_brl, p.name, c.name AS category_name,
               p.description, p.stock_quantity, p.status, p.specs
        FROM products p
        JOIN categories c ON c.category_id = p.category_id
        ORDER BY p.product_id
        LIMIT ?
    """
    return list(conn.execute(sql, (CATALOG_FETCH_LIMIT,)))


def fetch_promotions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    sql = """
        SELECT promotion_id, product_id, discount_percent, description, is_active
        FROM promotions
        ORDER BY promotion_id
        LIMIT ?
    """
    return list(conn.execute(sql, (CATALOG_FETCH_LIMIT,)))


def fetch_orders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    sql = """
        SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_brl,
               o.payment_method, o.tracking_code, o.estimated_delivery, o.notes,
               c.name AS customer_name, c.phone, c.email, c.city
        FROM orders o
        JOIN customers c ON c.customer_id = o.customer_id
        ORDER BY o.order_id
        LIMIT ?
    """
    return list(conn.execute(sql, (CATALOG_FETCH_LIMIT,)))


def fetch_order(conn: sqlite3.Connection, order_id: int) -> sqlite3.Row | None:
    sql = """
        SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_brl,
               o.payment_method, o.tracking_code, o.estimated_delivery, o.notes,
               c.name AS customer_name, c.phone, c.email, c.city
        FROM orders o
        JOIN customers c ON c.customer_id = o.customer_id
        WHERE o.order_id = ?
        LIMIT 1
    """
    return conn.execute(sql, (order_id,)).fetchone()


def fetch_order_items(conn: sqlite3.Connection, order_id: int) -> list[sqlite3.Row]:
    sql = """
        SELECT oi.quantity, p.name
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        WHERE oi.order_id = ?
        ORDER BY p.name
        LIMIT ?
    """
    return list(conn.execute(sql, (order_id, ORDER_ITEMS_LIMIT)))


def customers_with_email(conn: sqlite3.Connection, email: str) -> int:
    sql = "SELECT COUNT(*) AS n FROM customers WHERE lower(email) = lower(?) LIMIT 1"
    return int(conn.execute(sql, (email.strip(),)).fetchone()["n"])


def fetch_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    sql = """
        SELECT oi.order_id, oi.quantity, oi.product_id, p.price_brl, p.name, p.status
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        ORDER BY oi.order_id
        LIMIT ?
    """
    return list(conn.execute(sql, (CATALOG_FETCH_LIMIT,)))


def fetch_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    sql = "SELECT category_id, name FROM categories ORDER BY category_id LIMIT ?"
    return list(conn.execute(sql, (CATALOG_FETCH_LIMIT,)))


def last_order_date(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT MAX(order_date) AS day FROM orders LIMIT 1").fetchone()
    return date.fromisoformat(row["day"])
