"""Product states, code matching, and catalog filters."""

from decimal import Decimal

from music_store_agent.catalog import (
    CatalogQuery,
    effective_price,
    find_products,
    is_sellable,
    load_catalog,
    product_state,
    search_catalog,
)
from music_store_agent.constants import (
    SORT_PRICE_ASC,
    STATE_AVAILABLE,
    STATE_COMING_SOON,
    STATE_DISCONTINUED,
    STATE_OUT_OF_STOCK,
)
from music_store_agent.db import load_database
from music_store_agent.ledger import Ledger
from music_store_agent.textutil import description_conflicts


def _products():
    return load_catalog(load_database())


def _by_id(products, product_id):
    return next(product for product in products if product.product_id == product_id)


def test_states_and_brand_conflicts() -> None:
    products = _products()
    assert len(products) == 65
    assert product_state(_by_id(products, 81)) == STATE_AVAILABLE
    assert is_sellable(_by_id(products, 81))
    assert product_state(_by_id(products, 96)) == STATE_OUT_OF_STOCK
    assert product_state(_by_id(products, 136)) == STATE_DISCONTINUED
    assert _by_id(products, 136).details.stock > 0
    assert product_state(_by_id(products, 130)) == STATE_COMING_SOON
    conflicts = [
        product.product_id
        for product in products
        if description_conflicts(product.name, product.details.description)
    ]
    assert conflicts == [135, 137, 139, 140, 142, 144]


def test_budget_search_hides_unsellable_and_caps_rows() -> None:
    products = _products()
    text = search_catalog(
        products,
        CatalogQuery(text="violao", max_price=Decimal("1000")),
        Ledger(),
    )
    assert "Mostrando 1–5 de 12." in text
    assert "96" not in text
    assert "113" not in text


def test_codes_takamine_and_ukulele_concert() -> None:
    products = _products()
    gd20 = find_products(products, "GD-20")
    assert [product.product_id for product in gd20] == [95]
    assert len(find_products(products, "GD20")) == 1
    assert len(find_products(products, "Takamine")) == 4
    concert = search_catalog(products, CatalogQuery(text="ukulele concert"), Ledger())
    assert "CK-20" in concert or "KA-C" in concert
    assert "soprano" not in concert.casefold()


def test_empty_wind_category() -> None:
    products = _products()
    text = search_catalog(products, CatalogQuery(text="flauta"), Ledger())
    assert "não têm produtos à venda" in text


def test_category_spelling_is_normalised() -> None:
    products = _products()
    for spelling in ("violões", "Violão", "violao", "Violões"):
        request = CatalogQuery(category=spelling, max_price=Decimal("1000"))
        assert "de 12." in search_catalog(products, request, Ledger()), spelling
    unknown = search_catalog(products, CatalogQuery(category="xilofone"), Ledger())
    assert "Não conheço a categoria" in unknown


def test_words_outside_the_catalog_are_ignored_and_specs_count() -> None:
    products = _products()
    question = "Quais opções de violões disponíveis custando até R$1000?"
    text = search_catalog(products, CatalogQuery(question, max_price=Decimal("1000")), Ledger())
    assert "de 12." in text
    electric = find_products(products, "violão eletroacústico")
    assert electric
    assert all(("electronics", "yes") in product.details.specs for product in electric)
    cheap = search_catalog(products, CatalogQuery(text="violão preço baixo"), Ledger())
    assert "mais de uma família" not in cheap


def test_expensive_words_sort_from_the_top() -> None:
    products = _products()
    violoes = [p for p in products if p.category == "Violões" and is_sellable(p)]
    top = max(violoes, key=effective_price)
    text = search_catalog(products, CatalogQuery(text="o violão mais caro"), Ledger())
    assert text.splitlines()[1].startswith(top.name)
    cheap = search_catalog(products, CatalogQuery(text="violão", sort_by=SORT_PRICE_ASC), Ledger())
    assert not cheap.splitlines()[1].startswith(top.name)


def test_ids_and_empty_queries() -> None:
    products = _products()
    assert [product.product_id for product in find_products(products, "95")] == [95]
    assert [product.product_id for product in find_products(products, "id 95")] == [95]
    assert [product.product_id for product in find_products(products, "", 95)] == [95]
    assert find_products(products, "") == []
    assert find_products(products, "quanto custa") == []

