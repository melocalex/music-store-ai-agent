"""Write the data-quality report from the CSVs. Every finding is computed; nothing is dated."""

import re
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from music_store_agent.catalog import find_products, is_sellable, load_catalog, product_state
from music_store_agent.clock import pinned_day
from music_store_agent.constants import (
    ANIVERSARIO_MAX_PERCENT,
    ANIVERSARIO_MIN_PERCENT,
    BLACK_FRIDAY,
    BLACK_FRIDAY_MAX_PERCENT,
    BLACK_FRIDAY_MIN_PERCENT,
    CATALOG_FETCH_LIMIT,
    FREIGHT_FLAT,
    OPEN_DELIVERY_STATUSES,
    PAYMENT_PIX,
    PIX_PERCENT,
    STATE_AVAILABLE,
    STATE_COMING_SOON,
    STATE_DISCONTINUED,
    STATE_OUT_OF_STOCK,
    STATE_UNKNOWN,
    TRACKING_CODE_PATTERN,
)
from music_store_agent.db import (
    data_dir,
    fetch_categories,
    fetch_items,
    fetch_orders,
    fetch_promotions,
    last_order_date,
    load_database,
)
from music_store_agent.money import decide_installments, pix_price, split_parcels
from music_store_agent.textutil import description_conflicts, fold, format_brl

REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "data-quality.md"
_CREDIT_PREFIX = "credit_"
# Percent bands the manual gives per campaign. Other campaigns have no band.
_CAMPAIGN_BANDS = {
    "aniversario da loja": (ANIVERSARIO_MIN_PERCENT, ANIVERSARIO_MAX_PERCENT),
    fold(BLACK_FRIDAY): (BLACK_FRIDAY_MIN_PERCENT, BLACK_FRIDAY_MAX_PERCENT),
}

Row = tuple[str, str, str]


def render() -> str:
    conn = load_database(data_dir())
    rows = [
        _catalog(conn),
        _empty_categories(conn),
        _states(conn),
        _conflicts(conn),
        _duplicate_email(conn),
        _totals(conn),
        _pix_history(conn),
        _freight_history(conn),
        _installment_history(conn),
        _delivery_window(conn),
        _tracking(conn),
        _late_order(conn),
        _promo_band(conn),
        _black_friday(conn),
        _gd20(conn),
    ]
    body = "\n".join(
        f"| {finding} | {decision} | {eval_id} |" for finding, decision, eval_id in rows
    )
    return (
        "# Data quality\n\n"
        "Generated from the CSVs by `python -m music_store_agent.quality`. Each finding is "
        "computed from the data. Decisions are what the agent does. The eval id names the "
        "scenario in `evals/scenarios.yaml` that covers it, or `unit` for a pytest check.\n\n"
        "| Finding | Decision | Eval id |\n"
        "| --- | --- | --- |\n"
        f"{body}\n"
    )


def write_report(path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    return path


def _catalog(conn: sqlite3.Connection) -> Row:
    products = load_catalog(conn)
    sellable = sum(is_sellable(product) for product in products)
    categories = len(fetch_categories(conn))
    finding = f"{len(products)} products, {sellable} for sale, {categories} categories"
    return finding, "Answer with the catalog count, not the manual's 300+ claim", "catalog-count"


def _empty_categories(conn: sqlite3.Connection) -> Row:
    used = {product.category for product in load_catalog(conn)}
    names = [str(row["name"]) for row in fetch_categories(conn) if row["name"] not in used]
    finding = "Categories without products: " + ("; ".join(names) or "none")
    return finding, "Say the family is listed and has nothing for sale", "empty-winds"


def _states(conn: sqlite3.Connection) -> Row:
    states = (STATE_AVAILABLE, STATE_OUT_OF_STOCK, STATE_DISCONTINUED, STATE_COMING_SOON)
    counts = dict.fromkeys((*states, STATE_UNKNOWN), 0)
    for product in load_catalog(conn):
        counts[product_state(product)] += 1
    finding = (
        f"States: available {counts[STATE_AVAILABLE]}, out of stock {counts[STATE_OUT_OF_STOCK]}, "
        f"discontinued {counts[STATE_DISCONTINUED]}, coming soon {counts[STATE_COMING_SOON]}, "
        f"unknown status {counts[STATE_UNKNOWN]}"
    )
    decision = (
        "Sell only available items. Coming soon, discontinued, and an unknown status have no price"
    )
    return finding, decision, "coming-soon"


def _conflicts(conn: sqlite3.Connection) -> Row:
    ids = [
        str(product.product_id)
        for product in load_catalog(conn)
        if description_conflicts(product.name, product.details.description)
    ]
    finding = "Description brand conflicts: " + (", ".join(ids) or "none")
    return finding, "Drop the blurb and keep name, price, and specs", "unit"


def _duplicate_email(conn: sqlite3.Connection) -> Row:
    sql = """
        SELECT customer_id FROM customers
        WHERE lower(email) IN (
            SELECT lower(email) FROM customers GROUP BY lower(email) HAVING COUNT(*) > 1
        )
        ORDER BY customer_id
        LIMIT ?
    """
    ids = [str(row["customer_id"]) for row in conn.execute(sql, (CATALOG_FETCH_LIMIT,))]
    finding = "Customers sharing an email: " + (" and ".join(ids) or "none")
    decision = "A shared email needs the order's phone. Verification is order-scoped"
    return finding, decision, "unit"


def _totals(conn: sqlite3.Connection) -> Row:
    items = _item_sums(conn)
    stored = {int(row["order_id"]): _decimal(row["total_brl"]) for row in fetch_orders(conn)}
    gaps = [
        f"order {order_id} stored {total} vs items {items[order_id]}"
        for order_id, total in stored.items()
        if order_id in items and total != items[order_id]
    ]
    finding = "Stored totals that differ from the item sums: " + ("; ".join(gaps) or "none")
    return finding, "Report the stored total and never recompute history", "stored-total"


def _pix_history(conn: sqlite3.Connection) -> Row:
    items = _item_sums(conn)
    pix = {
        int(row["order_id"]): _decimal(row["total_brl"])
        for row in fetch_orders(conn)
        if row["payment_method"] == PAYMENT_PIX and int(row["order_id"]) in items
    }
    at_list = [str(order_id) for order_id, total in pix.items() if total == items[order_id]]
    at_pix = [
        str(order_id) for order_id, total in pix.items() if total == pix_price(items[order_id])
    ]
    finding = (
        f"PIX orders stored at the item sum: {', '.join(at_list) or 'none'}. "
        f"Stored at the item sum minus {PIX_PERCENT}%: {', '.join(at_pix) or 'none'}"
    )
    return finding, "Do not rewrite historical PIX totals", "stored-total"


def _freight_history(conn: sqlite3.Connection) -> Row:
    items = _item_sums(conn)
    with_freight = [
        str(row["order_id"])
        for row in fetch_orders(conn)
        if row["order_id"] in items
        and _decimal(row["total_brl"]) == items[row["order_id"]] + FREIGHT_FLAT
    ]
    finding = (
        f"Stored totals equal to the item sum plus the {format_brl(FREIGHT_FLAT)} freight: "
        f"{', '.join(with_freight) or 'none'}"
    )
    return finding, "Do not add freight back into a historical total", "history-freight"


def _installment_history(conn: sqlite3.Connection) -> Row:
    notes = []
    for row in fetch_orders(conn):
        method = str(row["payment_method"])
        count = _installments(method)
        if count is None:
            continue
        total = _decimal(row["total_brl"])
        flag = "" if decide_installments(total, count).allowed else ", below today's floor"
        parcel = split_parcels(total, count).rest
        notes.append(f"order {row['order_id']} {method} parcel {parcel}{flag}")
    finding = "Installment history: " + ("; ".join(notes) or "none")
    return finding, "History is not a precedent for the installment floors", "history-parcels"


def _installments(method: str) -> int | None:
    count = method.removeprefix(_CREDIT_PREFIX).removesuffix("x")
    if not method.startswith(_CREDIT_PREFIX) or not count.isdigit() or int(count) < 2:
        return None
    return int(count)


def _delivery_window(conn: sqlite3.Connection) -> Row:
    spans = [
        (_date(row["estimated_delivery"]) - _date(row["order_date"])).days
        for row in fetch_orders(conn)
        if row["estimated_delivery"]
    ]
    finding = (
        f"Stored estimates span {min(spans)}–{max(spans)} calendar days from the order"
        if spans
        else "No stored delivery estimates"
    )
    decision = (
        "A general question uses 1–3 business days. A specific order uses its stored estimate"
    )
    return finding, decision, "late-order"


def _tracking(conn: sqlite3.Connection) -> Row:
    pattern = re.compile(TRACKING_CODE_PATTERN)
    codes = [str(row["tracking_code"]) for row in fetch_orders(conn) if row["tracking_code"]]
    bad = [code for code in codes if pattern.fullmatch(code) is None]
    finding = f"{len(codes)} tracking codes, {len(bad)} outside BR + 9 + BR"
    decision = "Null tracking before dispatch is normal. Do not claim an order lacks a code"
    return finding, decision, "unit"


def _late_order(conn: sqlite3.Connection) -> Row:
    today = pinned_day(last_order_date(conn))
    late = [
        f"order {row['order_id']} ({row['status']}, estimate {row['estimated_delivery']})"
        for row in fetch_orders(conn)
        if row["status"] in OPEN_DELIVERY_STATUSES
        and row["estimated_delivery"]
        and _date(row["estimated_delivery"]) < today
    ]
    finding = f"Open orders past their estimate on {today.isoformat()}: " + (
        ", ".join(late) or "none"
    )
    decision = "Say the estimate passed and offer a handoff. Do not invent a resolution"
    return finding, decision, "late-order"


def _promo_band(conn: sqlite3.Connection) -> Row:
    outside = []
    unbanded: set[str] = set()
    for row in fetch_promotions(conn):
        band = _CAMPAIGN_BANDS.get(fold(str(row["description"])))
        percent = _decimal(row["discount_percent"])
        if band is None:
            unbanded.add(str(row["description"]))
        elif not band[0] <= percent <= band[1]:
            outside.append(f"{row['promotion_id']} {row['description']} {percent}%")
    finding = (
        "Promotions outside their campaign band in the manual: "
        f"{', '.join(outside) or 'none'}. Campaigns with no band: {', '.join(sorted(unbanded))}"
    )
    return finding, "Only an active promotion changes the price", "expired-promo"


def _black_friday(conn: sqlite3.Connection) -> Row:
    rows = [
        row for row in fetch_promotions(conn) if fold(BLACK_FRIDAY) in fold(str(row["description"]))
    ]
    active = sum(1 for row in rows if int(row["is_active"]) == 1)
    finding = f"{BLACK_FRIDAY} rows: {len(rows)}, active: {active}"
    decision = f"Answer only from is_active. {BLACK_FRIDAY} is not a current price"
    return finding, decision, "black-friday"


def _gd20(conn: sqlite3.Connection) -> Row:
    products = load_catalog(conn)
    notes = []
    for product in find_products(products, "GD20"):
        active = product.promos.campaign or "none"
        inactive = ", ".join(product.promos.inactive) or "none"
        notes.append(f"{product.name}: active promotion {active}; inactive {inactive}")
    finding = "; ".join(notes) or "GD20 not found"
    return finding, "Quote the current price and PIX. Do not emit the inactive percent", "gd20-code"


def _item_sums(conn: sqlite3.Connection) -> dict[int, Decimal]:
    sums: dict[int, Decimal] = {}
    for row in fetch_items(conn):
        line = _decimal(row["price_brl"]) * int(row["quantity"])
        sums[int(row["order_id"])] = sums.get(int(row["order_id"]), Decimal(0)) + line
    return sums


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _date(value: object) -> date:
    return date.fromisoformat(str(value))


def main() -> None:
    print(write_report())


if __name__ == "__main__":
    main()
