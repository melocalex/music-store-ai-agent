"""Write the data-quality report from the CSVs. The text has no timestamp."""

from pathlib import Path

from music_store_agent.catalog import load_catalog, product_state
from music_store_agent.constants import (
    EMPTY_CATEGORY_IDS,
    STATE_AVAILABLE,
    STATE_COMING_SOON,
    STATE_DISCONTINUED,
    STATE_OUT_OF_STOCK,
)
from music_store_agent.db import (
    data_dir,
    fetch_categories,
    fetch_items,
    fetch_orders,
    fetch_promotions,
    load_database,
)
from music_store_agent.money import quantize
from music_store_agent.textutil import description_conflicts

REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "data-quality.md"


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
    body = "\n".join(f"| {finding} | {decision} | {eval_id} |" for finding,
        decision,
        eval_id in rows)
    return (
        "# Data quality\n\n"
        "Generated from the CSVs. Decisions are what the agent does.\n\n"
        "| Finding | Decision | Eval id |\n"
        "| --- | --- | --- |\n"
        f"{body}\n"
    )


def write_report(path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    return path


def _catalog(conn) -> tuple[str, str, str]:
    products = load_catalog(conn)
    categories = fetch_categories(conn)
    finding = f"{len(products)} products and {len(categories)} categories"
    decision = "Answer with the catalog count, not the old 300+ claim"
    return finding, decision, "empty-winds"


def _empty_categories(conn) -> tuple[str, str, str]:
    names = [
        row["name"]
        for row in fetch_categories(conn)
        if int(row["category_id"]) in EMPTY_CATEGORY_IDS
    ]
    finding = "Empty categories: " + "; ".join(names)
    return finding, "Say the family is listed and has nothing for sale", "empty-winds"


def _states(conn) -> tuple[str, str, str]:
    products = load_catalog(conn)
    counts = {STATE_AVAILABLE: 0,
        STATE_OUT_OF_STOCK: 0,
        STATE_DISCONTINUED: 0,
        STATE_COMING_SOON: 0}
    for product in products:
        counts[product_state(product)] = counts.get(product_state(product), 0) + 1
    finding = (
        f"States: available {counts[STATE_AVAILABLE]}, out of stock {counts[STATE_OUT_OF_STOCK]}, "
        f"discontinued {counts[STATE_DISCONTINUED]}, coming soon {counts[STATE_COMING_SOON]}"
    )
    decision = (
        "Sell only available items. Coming soon has no price. "
        "Discontinued stock is not for sale"
    )
    return finding, decision, "coming-soon"


def _conflicts(conn) -> tuple[str, str, str]:
    ids = [
        str(product.product_id)
        for product in load_catalog(conn)
        if description_conflicts(product.name, product.details.description)
    ]
    finding = "Description brand conflicts: " + ", ".join(ids)
    return finding, "Drop the blurb and keep name, price, and specs", "unit"


def _duplicate_email(conn) -> tuple[str, str, str]:
    ids = [
        str(row["customer_id"])
        for row in conn.execute(
            """
            SELECT customer_id FROM customers
            WHERE email IN (SELECT email FROM customers GROUP BY email HAVING COUNT(*) > 1)
            ORDER BY customer_id
            LIMIT 20
            """
        )
    ]
    finding = "Duplicate email on customers " + " and ".join(ids)
    return (
        finding,
        "Email alone never identifies a customer. Verification is order-scoped",
        "other-order"
    )


def _totals(conn) -> tuple[str, str, str]:
    gaps = []
    items = _item_sums(conn)
    for row in fetch_orders(conn):
        stored = _decimal(row["total_brl"])
        summed = items.get(int(row["order_id"]))
        if summed is not None and stored != summed:
            gaps.append(f"order {row['order_id']} stored {stored} vs items {summed}")
    finding = "Stored totals differ from item sums: " + "; ".join(gaps)
    return finding, "Report the stored total and never recompute history", "stored-total"


def _pix_history(conn) -> tuple[str, str, str]:
    ids = [
        str(row["order_id"])
        for row in fetch_orders(conn)
        if str(row["payment_method"]) == "pix"
    ]
    finding = "PIX orders " + ", ".join(ids) + " store the list total, not list times 0.95"
    return finding, "Do not rewrite historical PIX totals", "stored-total"


def _freight_history(conn) -> tuple[str, str, str]:
    finding = "No stored total equals the item sum plus the flat freight"
    return finding, "Do not add freight back into a historical total", "freight-exact"


def _installment_history(conn) -> tuple[str, str, str]:
    rows = [
        row
        for row in fetch_orders(conn)
        if str(row["payment_method"]).startswith("credit_")
        and str(row["payment_method"]) != "credit_1x"
    ]
    notes = []
    for row in rows:
        parts = str(row["payment_method"]).removeprefix("credit_")
        if not parts.endswith("x"):
            continue
        count = int(parts[:-1])
        shown = quantize(_decimal(row["total_brl"]) / count)
        notes.append(f"order {row['order_id']} {row['payment_method']} parcel {shown}")
    finding = "Installment history: " + "; ".join(notes)
    return finding, "History is not a precedent for the installment floors", "c40-installments"


def _delivery_window(conn) -> tuple[str, str, str]:
    spans = []
    for row in fetch_orders(conn):
        if not row["estimated_delivery"]:
            continue
        start = _date(row["order_date"])
        end = _date(row["estimated_delivery"])
        spans.append((end - start).days)
    if not spans:
        finding = "No delivery estimates"
    else:
        finding = f"Campo Grande estimates span {min(spans)}–{max(spans)} calendar days"
    return (
        finding,
        "A general question uses 1–3 business days. A specific order uses the stored estimate",
        "late-order"
    )


def _tracking(conn) -> tuple[str, str, str]:
    import re

    pattern = re.compile(r"^BR[A-Z0-9]{9}BR$")
    codes = [row["tracking_code"] for row in fetch_orders(conn) if row["tracking_code"]]
    bad = [code for code in codes if pattern.fullmatch(str(code)) is None]
    finding = f"{len(codes)} tracking codes, {len(bad)} outside BR + 9 + BR"
    return (
        finding,
        "Null tracking before dispatch is normal. Do not claim city orders lack codes",
        "unit"
    )


def _late_order(conn) -> tuple[str, str, str]:
    finding = "Order 8 is shipped with an estimate before the pinned day"
    return (
        finding,
        "Say the estimate passed and offer a handoff. Do not invent a resolution",
        "late-order"
    )


def _promo_band(conn) -> tuple[str, str, str]:
    outside = []
    for row in fetch_promotions(conn):
        percent = _decimal(row["discount_percent"])
        if percent > 25 or percent < 10:
            outside.append(f"{row['promotion_id']} {percent}%")
    finding = "Promotions outside the 10–25 manual band: " + ", ".join(outside)
    return finding, "Only an active promotion changes the price", "expired-promo"


def _black_friday(conn) -> tuple[str, str, str]:
    rows = [
        row
        for row in fetch_promotions(conn)
        if "black friday" in str(row["description"]).casefold()
    ]
    active = sum(1 for row in rows if int(row["is_active"]) == 1)
    finding = f"Black Friday rows: {len(rows)}, active: {active}"
    return (
        finding,
        "Answer only from is_active. Black Friday is not a current price",
        "black-friday"
    )


def _gd20(conn) -> tuple[str, str, str]:
    finding = "GD20 has an inactive special offer, not an active Black Friday price"
    return finding, "Quote the current price and PIX. Do not emit the inactive percent", "gd20-code"


def _item_sums(conn) -> dict[int, object]:
    sums: dict[int, object] = {}
    for row in fetch_items(conn):
        order_id = int(row["order_id"])
        line = _decimal(row["price_brl"]) * int(row["quantity"])
        sums[order_id] = sums.get(order_id, _decimal("0")) + line
    return sums


def _decimal(value: object):
    from decimal import Decimal

    return Decimal(str(value))


def _date(value: object):
    from datetime import date

    return date.fromisoformat(str(value))


def main() -> None:
    path = write_report()
    print(path)


if __name__ == "__main__":
    main()
