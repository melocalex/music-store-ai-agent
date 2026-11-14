"""Phone matching, word amounts, and the brand-conflict rule."""

from decimal import Decimal

import pytest

from music_store_agent.constants import (
    DAILY_CAP_MESSAGE,
    LANDLINE_PHONE,
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
    STORE_EMAIL,
    WHATSAPP_PHONE,
)
from music_store_agent.textutil import (
    amounts_in_text,
    brands_in,
    code_tokens,
    description_conflicts,
    emails_match,
    mask_pii,
    parse_amount,
    percents_in_text,
    phones_match,
)

LUCAS = "(67) 99812-3456"


def test_full_phone_matches_and_last_digits_do_not() -> None:
    assert phones_match(LUCAS, "67998123456")
    assert phones_match(LUCAS, "+55 (67) 99812-3456")
    assert phones_match(LUCAS, "5567998123456")
    assert not phones_match(LUCAS, "9812-3456")
    assert not phones_match(LUCAS, "99812-3456")


def test_area_code_55_and_a_trunk_zero_still_match() -> None:
    santa_maria = "(55) 99123-4567"
    assert phones_match(santa_maria, "+55 55 99123-4567")
    assert phones_match(santa_maria, "5599123-4567")
    assert phones_match(LUCAS, "0 67 99812-3456")
    assert phones_match(LUCAS, "+55 0 67 99812-3456") is False
    assert not phones_match(santa_maria, "+55 67 99123-4567")


def test_email_is_exact_after_casefold() -> None:
    assert emails_match("Ana@Jmail.com", "ana@jmail.com")
    assert not emails_match("ana@jmail.com", "ana@jmail.com.br")


def test_money_forms_parse_to_the_same_amount() -> None:
    assert parse_amount("R$ 1.000") == Decimal("1000.00")
    assert parse_amount("1.000") == Decimal("1000.00")
    assert parse_amount("R$ 1000") == Decimal("1000.00")
    assert parse_amount("1.749,50") == Decimal("1749.50")
    assert parse_amount("2,199.00") == Decimal("2199.00")
    assert parse_amount("599,9") == Decimal("599.90")
    assert amounts_in_text("599,90 reais") == {Decimal("599.90")}
    assert amounts_in_text("1.749,50 reais") == {Decimal("1749.50")}
    assert amounts_in_text("R$ 1.749") == {Decimal("1749.00")}
    assert amounts_in_text("R$ 2,199.00") == {Decimal("2199.00")}
    assert amounts_in_text("6x de 99,98") == {Decimal("99.98")}
    assert amounts_in_text("BRL 599,90") == {Decimal("599.90")}


def test_non_money_numbers_are_not_amounts() -> None:
    assert amounts_in_text("pedido 4, 10x, 12 violões, nota 9,5") == set()
    assert amounts_in_text("2026-03-23, (67) 3321-4500, versão 2026.03.23") == set()
    assert amounts_in_text("CNPJ 12.345.678/0001-90, CEP 79202-333") == set()
    for bad in ("mil", "R$", "", "abc"):
        with pytest.raises(ValueError):
            parse_amount(bad)


def test_percents_are_read_in_digits() -> None:
    assert percents_in_text("15% de desconto e 12,5 %") == {Decimal("15"), Decimal("12.5")}
    assert percents_in_text("30 por cento") == {Decimal("30")}
    assert percents_in_text("pedido 15, 6x") == set()


def test_word_amounts_and_digit_reais() -> None:
    words = "mil e duzentos reais"
    cents = "quinhentos e noventa e nove reais e noventa centavos"
    assert Decimal("1200.00") in amounts_in_text(words)
    assert Decimal("599.90") in amounts_in_text(cents)
    assert Decimal("1200.00") in amounts_in_text("1200 reais")
    assert amounts_in_text("os reais motivos") == set()
    assert Decimal("10.00") in amounts_in_text("R$ 10,00")


def test_model_codes_do_not_fuzzy_match_neighbors() -> None:
    assert "gd20" in code_tokens("GD-20")
    assert "gd20" in code_tokens("gd 20")
    assert "gd20" in code_tokens("GD20")
    assert code_tokens("D-28").isdisjoint(code_tokens("D-28E"))
    assert code_tokens("C40").isdisjoint(code_tokens("C70"))


def test_brand_conflict_is_a_rule() -> None:
    assert description_conflicts("Tagima TW-55", "Um baixo Giannini de 4 cordas")
    assert not description_conflicts("Yamaha C40", "Violão clássico Yamaha")
    assert "takamine" in brands_in("Takamine GD20")


def test_mask_pii_hides_contacts_and_keeps_other_numbers() -> None:
    masked = mask_pii("Lucas, lucas.mendes@jmail.com, (67) 99812-3456, +55 67 99812-3456")
    assert "@" not in masked
    assert "99812" not in masked
    assert masked.count("[phone]") == 2
    kept = "Pedido 12345, rastreio BRAB1234567BR, data 2026-03-23, R$ 1.749,00, 6x"
    assert mask_pii(kept) == kept


def test_mask_pii_keeps_the_store_numbers_and_still_hides_the_customer() -> None:
    shown = mask_pii(f"{PROVIDER_ERROR_MESSAGE} Cliente: (67) 99812-3456.")
    assert f"WhatsApp {WHATSAPP_PHONE}." in shown
    assert "WhatsApp ([phone]" not in shown
    assert "99812" not in shown
    assert shown.count("[phone]") == 1
    for variant in ("+55 67 3321-4500", "067 3321-4500", "6733214500", "(67) 3341-4444"):
        assert mask_pii(f"Ligue {variant}.") == f"Ligue {variant}."
    assert mask_pii(f"Fixo {LANDLINE_PHONE}, cliente +55 67 99812-3456") == (
        f"Fixo {LANDLINE_PHONE}, cliente [phone]"
    )


def test_mask_pii_keeps_the_store_email_and_hides_the_customer_email() -> None:
    shown = mask_pii(f"Escreva para {STORE_EMAIL} ou responda lucas.mendes@jmail.com.")
    assert shown == f"Escreva para {STORE_EMAIL} ou responda [email]."
    assert mask_pii(STORE_EMAIL.upper()) == STORE_EMAIL.upper()


def test_store_messages_survive_masking_with_every_store_contact() -> None:
    for message in (
        PROVIDER_ERROR_MESSAGE,
        QUOTA_DAY_MESSAGE,
        RATE_LIMIT_MESSAGE,
        DAILY_CAP_MESSAGE,
    ):
        assert mask_pii(message) == message
    contacts = f"WhatsApp {WHATSAPP_PHONE}, fixo {LANDLINE_PHONE}, e-mail {STORE_EMAIL}."
    assert mask_pii(contacts) == contacts


def test_a_date_and_hour_is_not_a_phone() -> None:
    for text in (
        "A loja reabre em 2026-03-23 09:00.",
        "reabre em 2026-03-23 09:00",
        "Entrega em 23/03/2026 às 09:00.",
        "Pedido 12345, rastreio BRAB1234567BR.",
    ):
        assert mask_pii(text) == text


def test_customer_phones_are_masked_in_every_common_layout() -> None:
    for phone in (
        LUCAS,
        "+55 67 99812-3456",
        "+55 (67) 99812-3456",
        "067 99812-3456",
        "67 99812 3456",
        "67998123456",
        "(67) 3384-1200",
    ):
        assert mask_pii(f"Ligue {phone}, por favor.") == "Ligue [phone], por favor."
