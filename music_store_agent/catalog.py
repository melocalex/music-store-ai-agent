"""Catalog search, product states, and model-code matching."""

import json
import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from music_store_agent.constants import (
    SEARCH_ROW_CAP,
    SIMILAR_CAP,
    STATE_AVAILABLE,
    STATE_COMING_SOON,
    STATE_DISCONTINUED,
    STATE_OUT_OF_STOCK,
    STATUS_ACTIVE,
    STATUS_COMING_SOON,
    STATUS_DISCONTINUED,
)
from music_store_agent.db import fetch_products, fetch_promotions
from music_store_agent.ledger import Ledger
from music_store_agent.money import percent_off
from music_store_agent.textutil import (
    code_tokens,
    description_conflicts,
    fold,
    format_amount,
    format_brl,
)

_WIND = "sopro"
_ALIASES = {
    "violao": "Violões",
    "violoes": "Violões",
    "guitarra": "Guitarras",
    "guitarras": "Guitarras",
    "baixo": "Baixos",
    "baixos": "Baixos",
    "contrabaixo": "Baixos",
    "ukulele": "Ukuleles",
    "ukuleles": "Ukuleles",
    "bateria": "Baterias e Percussão",
    "baterias": "Baterias e Percussão",
    "percussao": "Baterias e Percussão",
    "teclado": "Teclados e Pianos",
    "teclados": "Teclados e Pianos",
    "piano": "Teclados e Pianos",
    "pianos": "Teclados e Pianos",
    "sopro": _WIND,
    "flauta": _WIND,
    "sax": _WIND,
    "saxofone": _WIND,
}
_SYNONYMS = {"eletroacustico": "eletrico", "eletroacusticos": "eletrico"}
_STOP = frozenset(
    "a o os as de do da das dos um uma e ou com sem para por em no na ate the an of to up under "
    "over me my is how much what which any algum alguma quais qual tem voce voces quero preco "
    "custa disponivel disponiveis ateh porfavor".split()
)
_WIND_NAMES = frozenset({"Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)"})


@dataclass(frozen=True)
class PromoSet:
    percent: Decimal | None
    campaign: str | None
    inactive: tuple[str, ...]


@dataclass(frozen=True)
class Details:
    status: str
    stock: int
    description: str
    specs: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Product:
    product_id: int
    name: str
    category: str
    list_price: Decimal
    details: Details
    promos: PromoSet


def effective_price(product: Product) -> Decimal:
    if product.promos.percent is None:
        return product.list_price
    return percent_off(product.list_price, product.promos.percent)


def product_state(product: Product) -> str:
    status = product.details.status
    stock = product.details.stock
    if status == STATUS_DISCONTINUED:
        return STATE_DISCONTINUED
    if status == STATUS_COMING_SOON:
        return STATE_COMING_SOON
    if status == STATUS_ACTIVE and stock <= 0:
        return STATE_OUT_OF_STOCK
    if status == STATUS_ACTIVE and stock > 0:
        return STATE_AVAILABLE
    return "unknown"


def is_sellable(product: Product) -> bool:
    return product_state(product) == STATE_AVAILABLE


def load_catalog(conn: sqlite3.Connection) -> tuple[Product, ...]:
    promos = _promo_map(fetch_promotions(conn))
    products = [_product_from(row,
        promos.get(row["product_id"],
        PromoSet(None,
        None,
        ()))) for row in fetch_products(conn)]
    return tuple(products)


def _promo_map(rows: list[sqlite3.Row]) -> dict[int, PromoSet]:
    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(int(row["product_id"]), []).append(row)
    return {product_id: _choose_promos(items) for product_id, items in grouped.items()}


def _choose_promos(items: list[sqlite3.Row]) -> PromoSet:
    active = [row for row in items if int(row["is_active"]) == 1]
    inactive = tuple(_promo_label(row) for row in items if int(row["is_active"]) != 1)
    if not active:
        return PromoSet(None, None, inactive)
    active.sort(key=lambda row: (-Decimal(row["discount_percent"]), int(row["promotion_id"])))
    winner = active[0]
    return PromoSet(Decimal(winner["discount_percent"]), str(winner["description"]), inactive)


def _promo_label(row: sqlite3.Row) -> str:
    return f"{row['description']} {row['discount_percent']}%"


def _product_from(row: sqlite3.Row, promos: PromoSet) -> Product:
    specs = _specs(str(row["specs"]))
    details = Details(str(row["status"]),
        int(row["stock_quantity"]),
        str(row["description"]),
        specs)
    return Product(
        int(row["product_id"]),
        str(row["name"]),
        str(row["category_name"]),
        Decimal(str(row["price_brl"])),
        details,
        promos,
    )


def _specs(raw: str) -> tuple[tuple[str, str], ...]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, dict):
        return ()
    return tuple((str(key), str(value)) for key, value in parsed.items())


@dataclass(frozen=True)
class CatalogQuery:
    text: str = ""
    category: str | None = None
    max_price: Decimal | None = None
    sort_by: str = "price_asc"
    offset: int = 0


def search_catalog(products: tuple[Product, ...], request: CatalogQuery, ledger: Ledger) -> str:
    query = request.text
    category = request.category
    max_price = request.max_price
    sort_by = request.sort_by
    offset = request.offset
    chosen, tokens, conflict = _interpret(query, category)
    if conflict:
        return "Há mais de uma família nesse pedido. Diga se é violão, guitarra, baixo ou ukulele."
    matched = _filter(products, chosen, tokens, max_price, sellable_only=True)
    ordered = _sort(matched, sort_by)
    return _page(ordered, offset, ledger, chosen)


def find_products(products: tuple[Product, ...], query: str) -> list[Product]:
    codes = code_tokens(query)
    if codes:
        hits = [product for product in products if codes & code_tokens(product.name)]
        if hits:
            return hits
    chosen, tokens, conflict = _interpret(query, None)
    if conflict:
        return []
    return _filter(products, chosen, tokens, None, sellable_only=False)


def _interpret(query: str, category: str | None) -> tuple[str | None, list[str], bool]:
    aliases = _aliases_in(query)
    if category:
        return category, _content_tokens(query), False
    if len(aliases) > 1:
        return None, [], True
    chosen = aliases[0] if aliases else None
    return chosen, _content_tokens(query), False


def _aliases_in(query: str) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[a-z0-9]+", fold(query)):
        name = _ALIASES.get(_SYNONYMS.get(token, token))
        if name and name not in found:
            found.append(name)
    return found


def _content_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", fold(query)):
        token = _SYNONYMS.get(token, token)
        if token in _STOP or token in _ALIASES or token.isdigit() or len(token) < 3:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _filter(
    products: tuple[Product, ...] | list[Product],
    category: str | None,
    tokens: list[str],
    max_price: Decimal | None,
    *,
    sellable_only: bool,
) -> list[Product]:
    pool = [product for product in products if _category_ok(product, category)]
    if tokens:
        pool = [product for product in pool if _tokens_ok(product, tokens)]
    if sellable_only:
        pool = [product for product in pool if is_sellable(product)]
    if max_price is not None:
        pool = [product for product in pool if effective_price(product) <= max_price]
    return pool


def _category_ok(product: Product, category: str | None) -> bool:
    if category is None:
        return True
    if category == _WIND:
        return product.category in _WIND_NAMES
    return product.category == category


def _tokens_ok(product: Product, tokens: list[str]) -> bool:
    words = set(re.findall(r"[a-z0-9]+", fold(product.name)))
    words.update(re.findall(r"[a-z0-9]+", fold(product.category)))
    codes = code_tokens(product.name)
    return all(token in words or token in codes for token in tokens)


def _sort(products: list[Product], sort_by: str) -> list[Product]:
    if sort_by == "name":
        return sorted(products, key=lambda product: fold(product.name))
    if sort_by == "price_desc":
        return sorted(products, key=effective_price, reverse=True)
    return sorted(products, key=lambda product: (effective_price(product), fold(product.name)))


def _page(products: list[Product], offset: int, ledger: Ledger, category: str | None) -> str:
    total = len(products)
    if total == 0:
        return _empty(category)
    start = max(0, offset)
    rows = products[start : start + SEARCH_ROW_CAP]
    if not rows:
        return f"Não há mais itens. O filtro tem {total}."
    lines = [f"Mostrando {start + 1}–{start + len(rows)} de {total}."]
    lines.extend(_hit(product, ledger) for product in rows)
    if start + len(rows) < total:
        lines.append("Peça o próximo bloco ou estreite o filtro.")
    return "\n".join(lines)


def _empty(category: str | None) -> str:
    if category == _WIND:
        return "Instrumentos de sopro estão no cadastro e não têm produtos à venda."
    if category:
        return f"A categoria {category} não tem itens à venda com esse filtro."
    return "Não encontrei itens à venda com esse filtro."


def _hit(product: Product, ledger: Ledger) -> str:
    price = effective_price(product)
    ledger.add_product(product.product_id, price)
    shown = format_brl(price)
    return (
        f"{product.name} | id {product.product_id} | {product.category} | "
        f"amount={format_amount(price)} | {shown}"
    )


def similar_products(products: tuple[Product, ...], product: Product) -> list[Product]:
    pool = [
        other
        for other in products
        if other.product_id != product.product_id
        and other.category == product.category
        and is_sellable(other)
    ]
    pool.sort(key=lambda other: (abs(effective_price(other) - product.list_price),
        fold(other.name)))
    return pool[:SIMILAR_CAP]


def describe_matches(products: tuple[Product, ...], found: list[Product], ledger: Ledger) -> str:
    if not found:
        return "Não encontrei esse modelo no catálogo."
    if len(found) > 1:
        lines = [f"Encontrei {len(found)} modelos. Qual deles?"]
        lines.extend(_hit(product, ledger) for product in found[:SEARCH_ROW_CAP])
        return "\n".join(lines)
    return describe_one(products, found[0], ledger)


def describe_one(products: tuple[Product, ...], product: Product, ledger: Ledger) -> str:
    state = product_state(product)
    if state == STATE_COMING_SOON:
        return _coming_soon(products, product, ledger)
    if state == STATE_DISCONTINUED:
        return _unavailable(products, product, ledger, "saiu do catálogo")
    if state == STATE_OUT_OF_STOCK:
        return _unavailable(products, product, ledger, "está sem unidades agora")
    return _available(product, ledger)


def _coming_soon(products: tuple[Product, ...], product: Product, ledger: Ledger) -> str:
    lines = [f"{product.name} é lançamento. Não está à venda e não prometo preço."]
    lines.extend(_similar_lines(products, product, ledger))
    return "\n".join(lines)


def _unavailable(
    products: tuple[Product, ...],
    product: Product,
    ledger: Ledger,
    reason: str,
) -> str:
    stock = product.details.stock
    lines = [f"{product.name} {reason}. Estoque gravado: {stock}. Não está à venda."]
    lines.append(_table_price(product, ledger))
    lines.extend(_similar_lines(products, product, ledger))
    return "\n".join(lines)


def _available(product: Product, ledger: Ledger) -> str:
    lines = [
        f"{product.name} está disponível. Categoria: {product.category}. "
        f"Estoque: {product.details.stock}."
    ]
    lines.append(_table_price(product, ledger))
    if product.promos.percent is not None:
        lines.append(_promo_price(product, ledger))
    else:
        lines.append(_pix_price(product, ledger))
    if product.promos.inactive:
        lines.append("Promoções encerradas, não aplicadas: " + "; ".join(product.promos.inactive))
    blurb = _safe_blurb(product)
    if blurb:
        lines.append(blurb)
    return "\n".join(lines)


def _table_price(product: Product, ledger: Ledger) -> str:
    ledger.add_product(product.product_id, product.list_price)
    shown = format_brl(product.list_price)
    amount = format_amount(product.list_price)
    return f"Preço de tabela product_id={product.product_id} amount={amount} {shown}."


def _promo_price(product: Product, ledger: Ledger) -> str:
    price = effective_price(product)
    ledger.add_product(product.product_id, price)
    shown = format_brl(price)
    percent = product.promos.percent
    campaign = product.promos.campaign
    return (
        f"Promoção ativa {campaign} {percent}%: "
        f"product_id={product.product_id} amount={format_amount(price)} {shown}. PIX não acumula."
    )


def _pix_price(product: Product, ledger: Ledger) -> str:
    from music_store_agent.money import pix_price

    price = pix_price(product.list_price)
    ledger.add_product(product.product_id, price)
    shown = format_brl(price)
    return f"PIX à vista product_id={product.product_id} amount={format_amount(price)} {shown}."


def _safe_blurb(product: Product) -> str:
    if description_conflicts(product.name, product.details.description):
        return "A ficha descritiva cita outra marca. Uso só nome, preço e especificações."
    return product.details.description


def _similar_lines(products: tuple[Product, ...], product: Product, ledger: Ledger) -> list[str]:
    similars = similar_products(products, product)
    if not similars:
        return ["Não há alternativa à venda na mesma família."]
    lines = ["Alternativas à venda:"]
    lines.extend(_hit(item, ledger) for item in similars)
    return lines


def active_promotion_text(products: tuple[Product, ...], ledger: Ledger) -> str:
    active = [
        product
        for product in products
        if product.promos.percent is not None and is_sellable(product)
    ]
    if not active:
        return "Nenhuma promoção ativa no catálogo. Black Friday não está ativa."
    lines = ["Promoções ativas. Black Friday não está entre elas."]
    lines.extend(_promo_price(product, ledger) for product in active[:SEARCH_ROW_CAP])
    return "\n".join(lines)
