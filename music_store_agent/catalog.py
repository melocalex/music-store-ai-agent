"""Catalog search, product states, and model-code matching."""

import json
import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from music_store_agent.constants import (
    BLACK_FRIDAY,
    OFFSET_MAX,
    SEARCH_ROW_CAP,
    SIMILAR_CAP,
    SORT_NAME,
    SORT_PRICE_ASC,
    SORT_PRICE_DESC,
    STATE_AVAILABLE,
    STATE_COMING_SOON,
    STATE_DISCONTINUED,
    STATE_OUT_OF_STOCK,
    STATE_UNKNOWN,
    STATUS_ACTIVE,
    STATUS_COMING_SOON,
    STATUS_DISCONTINUED,
)
from music_store_agent.db import fetch_products, fetch_promotions
from music_store_agent.ledger import Ledger
from music_store_agent.money import percent_off, pix_price
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
    "guitar": "Guitarras",
    "guitars": "Guitarras",
    "bass": "Baixos",
    "drum": "Baterias e Percussão",
    "drums": "Baterias e Percussão",
    "keyboard": "Teclados e Pianos",
    "keyboards": "Teclados e Pianos",
    "flute": _WIND,
}
# Rewritten before the alias lookup, so "preço baixo" is not the bass family.
_PHRASES = {
    "preco baixo": "barato",
    "valor baixo": "barato",
    "mais em conta": "barato",
    "acoustic guitar": "violao",
    "classical guitar": "violao",
    "electric guitar": "guitarra",
}
_SYNONYMS = {
    "eletroacustico": "eletrico",
    "eletroacusticos": "eletrico",
    "eletrica": "eletrico",
    "electric": "eletrico",
    "aco": "steel",
}
_SPEC_TAGS = {
    ("electronics", "yes"): ("eletrico",),
    ("strings", "steel"): ("steel",),
}
_EXPENSIVE = frozenset({"caro", "cara", "caros", "expensive", "top"})
_SORT_WORDS = _EXPENSIVE | {"barato", "barata", "baratos", "baratas", "cheap", "cheapest"}
# "não seja caro" asks for a cheap one: a negation up to three words before "caro" cancels it.
_NEGATIONS = frozenset({"nao", "nem", "sem", "not", "no"})
_NEGATION_REACH = 3
_STATE_LABELS = {
    STATE_AVAILABLE: "disponível",
    STATE_OUT_OF_STOCK: "sem estoque agora",
    STATE_DISCONTINUED: "fora de linha",
    STATE_COMING_SOON: "lançamento, ainda sem venda",
    STATE_UNKNOWN: "fora de venda",
}
_SPEC_LABELS = {
    "top": "tampo",
    "back_sides": "fundo e laterais",
    "neck": "braço",
    "strings": "cordas",
    "scale": "escala",
    "electronics": "captação",
    "color": "cor",
    "body": "corpo",
    "shells": "cascos",
    "pieces": "peças",
    "hardware": "ferragens",
    "keys": "teclas",
    "type": "tipo",
    "polyphony": "polifonia",
}
_SPEC_VALUES = {"yes": "sim", "no": "não", "steel": "aço", "included": "inclusas"}
_STOP = frozenset(
    "a o os as de do da das dos um uma e ou com sem para por em no na ate the an of to up under "
    "over me my is how much what which any algum alguma quais qual tem voce voces quero preco "
    "custa disponivel disponiveis ateh porfavor opcao opcoes custando custam quanto quantos "
    "modelo modelos mais menos bom boa melhor melhores vende vendem procuro procurando busco "
    "mostre mostrar liste listar gostaria loja instrumento instrumentos show list".split()
)
_WIND_NAMES = frozenset({"Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)"})
# "6 cordas" is a string count, not the word "cordas" in the 7-string names. A violão or guitar
# whose name carries no count has the standard six.
_STRING_COUNT = re.compile(r"\b(\d{1,2})\s*cordas?\b")
_STANDARD_STRINGS = 6
_SIX_STRING_FAMILIES = frozenset({"Violões", "Guitarras"})


@dataclass(frozen=True)
class PromoSet:
    percent: Decimal | None
    campaign: str | None
    inactive: tuple[str, ...]
    active: tuple[str, ...] = ()


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
    return STATE_UNKNOWN


def is_sellable(product: Product) -> bool:
    return product_state(product) == STATE_AVAILABLE


def load_catalog(conn: sqlite3.Connection) -> tuple[Product, ...]:
    promos = _promo_map(fetch_promotions(conn))
    products = [
        _product_from(row, promos.get(row["product_id"], PromoSet(None, None, ())))
        for row in fetch_products(conn)
    ]
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
    campaigns = tuple(str(row["description"]) for row in active)
    percent = Decimal(winner["discount_percent"])
    return PromoSet(percent, str(winner["description"]), inactive, campaigns)


def _promo_label(row: sqlite3.Row) -> str:
    return f"{row['description']} {row['discount_percent']}%"


def _product_from(row: sqlite3.Row, promos: PromoSet) -> Product:
    specs = _specs(str(row["specs"]))
    details = Details(
        str(row["status"]), int(row["stock_quantity"]), str(row["description"]), specs
    )
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
    sort_by: str | None = None
    offset: int = 0


def search_catalog(products: tuple[Product, ...], request: CatalogQuery, ledger: Ledger) -> str:
    family = None
    if request.category:
        family = resolve_category(request.category, products)
        if family is None:
            names = ", ".join(sorted({product.category for product in products}))
            return f"Não conheço a categoria {request.category}. Use uma destas: {names}."
    strings, text = _string_count(request.text)
    chosen, tokens, conflict = _interpret(text, family)
    if conflict:
        return "Há mais de uma família nesse pedido. Diga se é violão, guitarra, baixo ou ukulele."
    ignored = [token for token in tokens if token not in _vocabulary(products) | _SORT_WORDS]
    if ignored and len(ignored) == len(tokens) and chosen is None:
        return _not_in_catalog(products, ignored)
    matched = _filter(products, chosen, tokens, request.max_price, sellable_only=True)
    matched = [product for product in matched if _has_strings(product, strings)]
    ordered = _sort(matched, _sort_order(request))
    text = _page(ordered, request.offset, ledger, chosen)
    if ignored:
        text += f"\nSem correspondência no catálogo, ignorei: {', '.join(ignored)}."
    if request.max_price is None:
        return text
    ledger.add_budget(request.max_price)
    ceiling = f"amount={format_amount(request.max_price)} {format_brl(request.max_price)}"
    return f"Teto pedido pelo cliente: product_id=null {ceiling}.\n{text}"


def _not_in_catalog(products: tuple[Product, ...], words: list[str]) -> str:
    families = ", ".join(sorted({product.category for product in products if is_sellable(product)}))
    return f"Não encontrei {' '.join(words)} no catálogo. Famílias à venda: {families}."


def resolve_category(raw: str, products: tuple[Product, ...]) -> str | None:
    """Accept "Violão", "violões", "violao", or the exact catalog name."""
    folded = fold(raw).strip()
    for name in {product.category for product in products} | _WIND_NAMES:
        if fold(name) == folded:
            return name
    aliases = _aliases_in(raw)
    return aliases[0] if len(aliases) == 1 else None


def find_products(
    products: tuple[Product, ...], query: str, product_id: int | None = None
) -> list[Product]:
    """Exact id, then model code, then words. A query with no usable word matches nothing."""
    asked = product_id if product_id is not None else _id_in(query)
    if asked is not None:
        return [product for product in products if product.product_id == asked]
    codes = code_tokens(query)
    if codes:
        hits = [product for product in products if codes & code_tokens(product.name)]
        if hits:
            return hits
    strings, text = _string_count(query)
    chosen, tokens, conflict = _interpret(text, None)
    if conflict:
        return []
    tokens = [token for token in tokens if token in _vocabulary(products)]
    if chosen is None and not tokens and strings is None:
        return []
    pool = _filter(products, chosen, tokens, None, sellable_only=False)
    return [product for product in pool if _has_strings(product, strings)]


def _string_count(text: str) -> tuple[int | None, str]:
    """The string count asked for, if any, and the text without it."""
    folded = fold(text)
    match = _STRING_COUNT.search(folded)
    if match is None:
        return None, text
    return int(match.group(1)), folded[: match.start()] + folded[match.end() :]


def _has_strings(product: Product, strings: int | None) -> bool:
    if strings is None:
        return True
    named = _STRING_COUNT.search(fold(product.name))
    if named is not None:
        return int(named.group(1)) == strings
    return strings == _STANDARD_STRINGS and product.category in _SIX_STRING_FAMILIES


def _id_in(query: str) -> int | None:
    match = re.fullmatch(r"(?:id|produto|product_id)?\s*#?\s*(\d+)", fold(query).strip())
    return int(match.group(1)) if match else None


def _interpret(query: str, category: str | None) -> tuple[str | None, list[str], bool]:
    if category:
        return category, _content_tokens(query), False
    aliases = _aliases_in(query)
    if len(aliases) > 1:
        return None, [], True
    chosen = aliases[0] if aliases else None
    return chosen, _content_tokens(query), False


def _normalized(query: str) -> str:
    text = fold(query)
    for phrase, replacement in _PHRASES.items():
        text = text.replace(phrase, replacement)
    return text


def _aliases_in(query: str) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[a-z0-9]+", _normalized(query)):
        name = _ALIASES.get(_SYNONYMS.get(token, token))
        if name and name not in found:
            found.append(name)
    return found


def _content_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", _normalized(query)):
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
    known = _vocabulary(products)
    useful = [token for token in tokens if token in known]
    pool = [product for product in products if _category_ok(product, category)]
    if useful:
        pool = [product for product in pool if set(useful) <= _words(product)]
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


def _words(product: Product) -> set[str]:
    """Name, category, and spec words. Descriptions are left out: six name another brand."""
    words = set(re.findall(r"[a-z0-9]+", fold(product.name)))
    words.update(re.findall(r"[a-z0-9]+", fold(product.category)))
    for key, value in product.details.specs:
        words.update(re.findall(r"[a-z0-9]+", fold(value)))
        words.update(_SPEC_TAGS.get((key, fold(value)), ()))
    words.update(code_tokens(product.name))
    return words


def _vocabulary(products: tuple[Product, ...] | list[Product]) -> set[str]:
    known: set[str] = set()
    for product in products:
        known.update(_words(product))
    return known


def _sort_order(request: CatalogQuery) -> str:
    """An explicit sort wins. Without one, "caro" sorts from the top, unless it is negated."""
    if request.sort_by is not None:
        return request.sort_by
    words = re.findall(r"[a-z]+", _normalized(request.text))
    for index, word in enumerate(words):
        negated = _NEGATIONS.intersection(words[max(0, index - _NEGATION_REACH) : index])
        if word in _EXPENSIVE and not negated:
            return SORT_PRICE_DESC
    return SORT_PRICE_ASC


def _sort(products: list[Product], sort_by: str) -> list[Product]:
    if sort_by == SORT_NAME:
        return sorted(products, key=lambda product: fold(product.name))
    if sort_by == SORT_PRICE_DESC:
        return sorted(products, key=effective_price, reverse=True)
    return sorted(products, key=lambda product: (effective_price(product), fold(product.name)))


def _page(products: list[Product], offset: int, ledger: Ledger, category: str | None) -> str:
    total = len(products)
    if total == 0:
        return _empty(category)
    start = min(max(0, offset), OFFSET_MAX)
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


def promo_text(product: Product) -> str | None:
    """The manual asks for the original price and the percent next to every promo price."""
    if product.promos.percent is None:
        return None
    original = format_brl(product.list_price)
    price = format_brl(effective_price(product))
    return f"de {original} por {price} ({product.promos.campaign}, {product.promos.percent}%)"


def _hit(product: Product, ledger: Ledger) -> str:
    price = effective_price(product)
    ledger.add_product(product.product_id, price, product.name)
    shown = format_brl(price)
    row = (
        f"{product.name} | id {product.product_id} | {product.category} | "
        f"amount={format_amount(price)} | {shown}"
    )
    promo = promo_text(product)
    if promo is None:
        return row
    ledger.add_product(product.product_id, product.list_price, product.name)
    return f"{row} | promoção {promo}"


def similar_products(products: tuple[Product, ...], product: Product) -> list[Product]:
    pool = [
        other
        for other in products
        if other.product_id != product.product_id
        and other.category == product.category
        and is_sellable(other)
    ]
    pool.sort(
        key=lambda other: (abs(effective_price(other) - product.list_price), fold(other.name))
    )
    return pool[:SIMILAR_CAP]


def describe_matches(products: tuple[Product, ...], found: list[Product], ledger: Ledger) -> str:
    if not found:
        return "Não encontrei esse modelo no catálogo."
    if len(found) > 1:
        lines = [f"Encontrei {len(found)} modelos. Qual deles?"]
        lines.extend(_match_line(product, ledger) for product in found[:SEARCH_ROW_CAP])
        return "\n".join(lines)
    return describe_one(products, found[0], ledger)


def _match_line(product: Product, ledger: Ledger) -> str:
    """A model that is not for sale is listed with its state and no price."""
    if is_sellable(product):
        return _hit(product, ledger)
    label = _STATE_LABELS[product_state(product)]
    return f"{product.name} | id {product.product_id} | {product.category} | {label}, sem preço"


def describe_one(products: tuple[Product, ...], product: Product, ledger: Ledger) -> str:
    state = product_state(product)
    if state == STATE_COMING_SOON:
        return _coming_soon(products, product, ledger)
    if state == STATE_DISCONTINUED:
        return _unavailable(products, product, ledger, "saiu do catálogo")
    if state == STATE_OUT_OF_STOCK:
        return _unavailable(products, product, ledger, "está sem unidades agora")
    if state == STATE_AVAILABLE:
        return _available(product, ledger)
    return _unavailable(products, product, ledger, "tem um status que não permite venda")


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
    lines = [f"{product.name} {reason}. Estoque gravado: {stock}."]
    lines.append("Não está à venda, então não cito preço.")
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
    specs = spec_text(product)
    if specs:
        lines.append(specs)
    return "\n".join(lines)


def spec_text(product: Product) -> str:
    parts = [
        f"{_SPEC_LABELS.get(key, key)} {_SPEC_VALUES.get(value, value)}"
        for key, value in product.details.specs
    ]
    return "Especificações: " + "; ".join(parts) + "." if parts else ""


def _table_price(product: Product, ledger: Ledger) -> str:
    ledger.add_product(product.product_id, product.list_price, product.name)
    shown = format_brl(product.list_price)
    amount = format_amount(product.list_price)
    return f"Preço de tabela product_id={product.product_id} amount={amount} {shown}."


def _promo_price(product: Product, ledger: Ledger) -> str:
    price = effective_price(product)
    ledger.add_product(product.product_id, price, product.name)
    ledger.add_product(product.product_id, product.list_price, product.name)
    return (
        f"Promoção ativa {product.name}, {promo_text(product)}: "
        f"product_id={product.product_id} amount={format_amount(price)} "
        f"preço original amount={format_amount(product.list_price)}. PIX não acumula."
    )


def _pix_price(product: Product, ledger: Ledger) -> str:
    price = pix_price(product.list_price)
    ledger.add_product(product.product_id, price, product.name)
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
    black_friday = [
        product
        for product in products
        if any(fold(BLACK_FRIDAY) in fold(campaign) for campaign in product.promos.active)
    ]
    if black_friday:
        status = f"{BLACK_FRIDAY} está ativa em {len(black_friday)} itens."
    else:
        status = f"{BLACK_FRIDAY} não está entre as promoções ativas."
    if not active:
        return f"Nenhuma promoção ativa no catálogo. {status}"
    lines = [f"Promoções ativas: {len(active)}. {status}"]
    lines.extend(_promo_price(product, ledger) for product in active[:SEARCH_ROW_CAP])
    return "\n".join(lines)
