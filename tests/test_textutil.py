"""Phone matching, word amounts, and the brand-conflict rule."""

from decimal import Decimal

from music_store_agent.textutil import (
    amounts_in_text,
    brands_in,
    code_tokens,
    description_conflicts,
    emails_match,
    phones_match,
)

LUCAS = "(67) 99812-3456"


def test_full_phone_matches_and_last_digits_do_not() -> None:
    assert phones_match(LUCAS, "67998123456")
    assert phones_match(LUCAS, "+55 (67) 99812-3456")
    assert phones_match(LUCAS, "5567998123456")
    assert not phones_match(LUCAS, "9812-3456")
    assert not phones_match(LUCAS, "99812-3456")


def test_email_is_exact_after_casefold() -> None:
    assert emails_match("Ana@Jmail.com", "ana@jmail.com")
    assert not emails_match("ana@jmail.com", "ana@jmail.com.br")


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
