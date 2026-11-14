"""Product states, code matching, and catalog filters."""

from dataclasses import replace
from decimal import Decimal

from music_store_agent.catalog import (
    CatalogQuery,
    PromoSet,
    active_promotion_text,
    describe_matches,
    describe_one,
    effective_price,
    find_products,
    is_sellable,
    load_catalog,
    product_state,
    search_catalog,
)
from music_store_agent.constants import (
    BLACK_FRIDAY,
    CENT,
    SEARCH_ROW_CAP,
    SORT_PRICE_ASC,
    STATE_AVAILABLE,
    STATE_COMING_SOON,
    STATE_DISCONTINUED,
    STATE_OUT_OF_STOCK,
    STATE_UNKNOWN,
)
from music_store_agent.db import load_database
from music_store_agent.ledger import Ledger
from music_store_agent.textutil import description_conflicts, format_brl


def _products():
    return load_catalog(load_database())


def _by_id(products, product_id):
    return next(product for product in products if product.product_id == product_id)


def test_states_and_brand_conflicts() -> None:
    conn = load_database()
    products = load_catalog(conn)
    stored = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    assert len(products) == stored
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


def test_a_parcel_count_in_the_query_is_not_a_model_code() -> None:
    products = _products()
    assert [p.product_id for p in find_products(products, "C40 em 4x")] == [81]
    assert [p.product_id for p in find_products(products, "Bass 4X")] == [138]
    assert [p.product_id for p in find_products(products, "yamaha bass 3x")] == [137]
    assert find_products(products, "4x") == []


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


def test_a_search_with_no_catalog_word_says_so_and_lists_the_families() -> None:
    products = _products()
    for word in ("amplificador", "violino", "cavaquinho"):
        ledger = Ledger()
        text = search_catalog(products, CatalogQuery(word), ledger)
        assert text.startswith(f"Não encontrei {word} no catálogo.")
        assert "Violões" in text and "Ukuleles" in text
        assert "Mostrando" not in text
        assert ledger.by_product == {}


def test_a_search_names_the_words_it_ignored() -> None:
    products = _products()
    violoes = sum(1 for p in products if p.category == "Violões" and is_sellable(p))
    text = search_catalog(products, CatalogQuery("violão canhoto"), Ledger())
    assert f"de {violoes}." in text
    assert text.endswith("Sem correspondência no catálogo, ignorei: canhoto.")
    for known in ("ukulele concert", "violão barato", "o violão mais caro"):
        assert "ignorei" not in search_catalog(products, CatalogQuery(known), Ledger()), known


def test_a_string_count_is_a_filter_not_the_word_cordas() -> None:
    products = _products()
    seven = [p for p in products if "7 Cordas" in p.name and is_sellable(p)]
    six = [
        p for p in products if p.category == "Violões" and is_sellable(p) and "Cordas" not in p.name
    ]
    text = search_catalog(products, CatalogQuery("violão de 6 cordas"), Ledger())
    assert f"de {len(six)}." in text
    assert "7 Cordas" not in text
    sevens = search_catalog(products, CatalogQuery("violão de 7 cordas"), Ledger())
    assert f"de {len(seven)}." in sevens
    for twelve in ("12 cordas", "violão 12 cordas"):
        assert "Mostrando" not in search_catalog(products, CatalogQuery(twelve), Ledger())
    looked_up = find_products(products, "violão de 6 cordas")
    assert looked_up and all("Cordas" not in p.name for p in looked_up)


def test_expensive_words_sort_from_the_top() -> None:
    products = _products()
    violoes = [p for p in products if p.category == "Violões" and is_sellable(p)]
    top = max(violoes, key=effective_price)
    text = search_catalog(products, CatalogQuery(text="o violão mais caro"), Ledger())
    assert text.splitlines()[1].startswith(top.name)
    cheap = search_catalog(products, CatalogQuery(text="violão", sort_by=SORT_PRICE_ASC), Ledger())
    assert not cheap.splitlines()[1].startswith(top.name)


def test_an_explicit_sort_and_a_negated_caro_keep_the_cheapest_first() -> None:
    products = _products()
    violoes = [p for p in products if p.category == "Violões" and is_sellable(p)]
    cheapest = min(violoes, key=lambda p: (effective_price(p), p.name))
    for request in (
        CatalogQuery(text="violão que não seja caro"),
        CatalogQuery(text="violão caro", sort_by=SORT_PRICE_ASC),
    ):
        first = search_catalog(products, request, Ledger()).splitlines()[1]
        assert first.startswith(cheapest.name), request
    top = max(violoes, key=effective_price)
    most = search_catalog(products, CatalogQuery(text="violão caro"), Ledger()).splitlines()[1]
    assert most.startswith(top.name)


def test_ids_and_empty_queries() -> None:
    products = _products()
    assert [product.product_id for product in find_products(products, "95")] == [95]
    assert [product.product_id for product in find_products(products, "id 95")] == [95]
    assert [product.product_id for product in find_products(products, "", 95)] == [95]
    assert find_products(products, "") == []
    assert find_products(products, "quanto custa") == []


def test_several_matches_hide_prices_of_unsellable_models() -> None:
    products = _products()
    ledger = Ledger()
    text = describe_matches(products, find_products(products, "Kala barítono"), ledger)
    coming = _by_id(products, 130)
    assert format_brl(coming.list_price) not in text
    assert "lançamento" in text
    assert 130 not in ledger.by_product
    assert 128 in ledger.by_product


def test_discontinued_and_unknown_states_carry_no_price() -> None:
    products = _products()
    ledger = Ledger()
    bass = _by_id(products, 136)
    text = describe_one(products, bass, ledger)
    assert format_brl(bass.list_price) not in text
    assert 136 not in ledger.by_product
    c40 = _by_id(products, 81)
    odd = replace(c40, details=replace(c40.details, status="archived"))
    assert product_state(odd) == STATE_UNKNOWN
    assert not is_sellable(odd)
    unknown = describe_one(products, odd, ledger)
    assert "não permite venda" in unknown
    assert 81 not in ledger.by_product


def test_more_matches_than_rows_say_how_many_and_discontinued_hides_stock() -> None:
    products = _products()
    yamaha = find_products(products, "Yamaha")
    assert len(yamaha) > SEARCH_ROW_CAP
    text = describe_matches(products, yamaha, Ledger())
    assert f"Mostrando {SEARCH_ROW_CAP} de {len(yamaha)}." in text
    two = describe_matches(products, find_products(products, "Takamine")[:2], Ledger())
    assert "Mostrando" not in two
    bass = _by_id(products, 136)
    assert product_state(bass) == STATE_DISCONTINUED and bass.details.stock > 0
    assert "Estoque" not in describe_one(products, bass, Ledger())
    sold_out = next(p for p in products if product_state(p) == STATE_OUT_OF_STOCK)
    assert "Estoque gravado: 0." in describe_one(products, sold_out, Ledger())


def test_specs_are_shown() -> None:
    products = _products()
    text = describe_one(products, _by_id(products, 81), Ledger())
    assert "Especificações:" in text
    assert "650mm" in text


def test_black_friday_status_comes_from_the_data() -> None:
    products = _products()
    assert f"{BLACK_FRIDAY} não está" in active_promotion_text(products, Ledger())
    c40 = _by_id(products, 81)
    promo = PromoSet(Decimal("20"), BLACK_FRIDAY, (), (BLACK_FRIDAY,))
    on_sale = replace(c40, promos=promo)
    assert f"{BLACK_FRIDAY} está ativa em 1" in active_promotion_text((on_sale,), Ledger())


def test_price_cap_includes_the_exact_price() -> None:
    products = _products()
    c40 = _by_id(products, 81)
    price = effective_price(c40)
    at_cap = search_catalog(products, CatalogQuery("C40", max_price=price), Ledger())
    below = search_catalog(products, CatalogQuery("C40", max_price=price - CENT), Ledger())
    assert c40.name in at_cap
    assert c40.name not in below
