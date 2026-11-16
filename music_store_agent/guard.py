"""Reject prices and percents that a tool did not return for that product."""

import re
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from music_store_agent.ledger import (
    BUDGET,
    FLOOR,
    FREIGHT,
    ORDER_TOTAL,
    RULE,
    THRESHOLD,
    Ledger,
    RuleKind,
)
from music_store_agent.textutil import (
    amount_spans,
    amounts_in_text,
    budget_caps,
    code_tokens,
    fold,
    parse_amount,
    percents_in_text,
)

# A sentence ends at ! ? ; a newline, or a period that is not a decimal point.
_BOUNDARY = re.compile(r"[!?;\n]|\.(?!\d)")
_CODE_SPAN = 3
# "o C40 custa R$ 849,00": a singular price verb right after a product binds the next amount to
# that product. A plural verb ("custam") or a list ("respectivamente") binds nothing.
_PRICE_VERB = re.compile(r"\b(?:custa|sai|fica|vale|esta|por|costs|is|for)\b")
_BINDING_GAP_WORDS = 6
# A rule value may share a sentence with a product only next to a word of its own kind, so
# "o frete do C40 é R$ 35,00" passes and "o C40 custa R$ 35,00" does not.
_KIND_WORDS: dict[RuleKind, tuple[str, ...]] = {
    FREIGHT: ("frete", "fretes", "entrega", "envio", "shipping", "freight", "delivery"),
    FLOOR: ("minima", "minimo", "minimas", "minimos", "piso", "minimum", "pelo menos", "at least"),
    THRESHOLD: ("acima", "a partir", "mais de", "superior", "above", "over"),
    ORDER_TOTAL: ("total", "pedido", "pago", "paga", "order", "paid"),
    BUDGET: (
        "ate",
        "teto",
        "orcamento",
        "limite",
        "abaixo",
        "menos de",
        "budget",
        "up to",
        "under",
        "below",
        "within",
        "dentro",
        "maximo",
        "ou menos",
        "or less",
        "cabem",
        "cabe",
        "fit",
        "fits",
    ),
    RULE: ("regra", "manual", "politica", "rule", "policy"),
}


class PriceQuote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product_id: int | None = None
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def _parse(cls, value: object) -> Decimal:
        return parse_amount(value)


class AgentReply(BaseModel):
    """Customer text plus the price rows that support it."""

    model_config = ConfigDict(extra="ignore")
    message: str
    quotes: list[PriceQuote] = Field(default_factory=list)


@dataclass(frozen=True)
class GroundingGap:
    message_amounts: tuple[str, ...]
    bad_quotes: tuple[str, ...]
    crossed: tuple[str, ...] = ()
    percents: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.message_amounts or self.bad_quotes or self.crossed or self.percents)


def grounding_gap(
    message: str,
    quotes: list[PriceQuote],
    ledger: Ledger,
    catalog: dict[int, str] | None = None,
    caps: frozenset[Decimal] | set[Decimal] = frozenset(),
) -> GroundingGap:
    """`catalog` maps product ids to names, so a product named without a lookup still counts.

    `caps` are the upper bounds the customer's own message states, such as "até R$ 1.500". The
    reply may repeat one only as a bound, in a sentence that says so. It is the customer's limit,
    not a price the store asserts, so it needs no quote.
    """
    amounts = amounts_in_text(message)
    quoted = [quote.amount for quote in quotes]
    echoed = _echoed_caps(message, set(caps))
    missing = [
        str(amount) for amount in sorted(amounts) if amount not in quoted and amount not in echoed
    ]
    bad = [_label(q.product_id, q.amount) for q in quotes if not _quote_ok(q, ledger)]
    percents = [str(value) for value in sorted(percents_in_text(message) - ledger.percents)]
    every = amounts | set(quoted)
    unknown = [str(amount) for amount in sorted(every) if not ledger.knows(amount)]
    return GroundingGap(
        tuple(missing),
        tuple(bad),
        tuple(_crossed(message, quotes, {**ledger.names, **(catalog or {})}, ledger)),
        tuple(percents),
        tuple(unknown),
    )


def _echoed_caps(message: str, caps: set[Decimal]) -> set[Decimal]:
    """Customer caps that the reply writes only as a bound, never as a bare amount."""
    if not caps:
        return set()
    bounded: set[Decimal] = set()
    loose: set[Decimal] = set()
    for sentence in _BOUNDARY.split(message):
        said = budget_caps(sentence) & caps
        bounded |= said
        loose |= amounts_in_text(sentence) - said
    return bounded - loose


def _label(product_id: int | None, amount: Decimal) -> str:
    label = "policy" if product_id is None else str(product_id)
    return f"{label}:{amount}"


def _quote_ok(quote: PriceQuote, ledger: Ledger) -> bool:
    if quote.product_id is None:
        return ledger.policy_has(quote.amount)
    return ledger.product_has(quote.product_id, quote.amount)


def _crossed(
    message: str, quotes: list[PriceQuote], names: dict[int, str], ledger: Ledger
) -> list[str]:
    """A sentence that names products may only carry prices quoted for one of them.

    A null-id value may sit there too, but only next to a word of its kind: a freight, a
    floor, a threshold, an order total, or the customer's budget.
    """
    owners: dict[Decimal, set[int | None]] = {}
    for quote in quotes:
        owners.setdefault(quote.amount, set()).add(quote.product_id)
    codes = _codes(names)
    crossed: list[str] = []
    for sentence in _BOUNDARY.split(message):
        named = _named(sentence, codes)
        if not named:
            continue
        crossed.extend(_swapped(sentence, owners, codes))
        for amount in sorted(amounts_in_text(sentence)):
            ids = owners.get(amount, set())
            if not ids or not named.isdisjoint(ids):
                continue
            if None in ids and _names_kind(sentence, ledger.rule_kinds(amount)):
                continue
            products = sorted(i for i in ids if i is not None)
            crossed.append(_label(products[0] if products else None, amount))
    return crossed


def _swapped(
    sentence: str, owners: dict[Decimal, set[int | None]], codes: dict[str, set[int]]
) -> list[str]:
    """A product price bound by a price verb to the nearest product before it must be its own.

    "O C40 custa R$ 849,00 e o C70 custa R$ 599,90" names both models, so the sentence check
    alone lets the swap through. Here each amount goes to the product right before it.
    """
    folded = fold(sentence)
    mentions = _mentions(folded, codes)
    swapped: list[str] = []
    for start, amount in amount_spans(folded):
        ids = owners.get(amount, set())
        before = [mention for mention in mentions if mention[0] <= start]
        if not ids or None in ids or not before:
            continue
        end, nearest = before[-1]
        gap = folded[end:start]
        bound = len(gap.split()) <= _BINDING_GAP_WORDS and _PRICE_VERB.search(gap)
        if bound and nearest.isdisjoint(ids):
            swapped.append(_label(min(i for i in ids if i is not None), amount))
    return swapped


def _mentions(folded: str, codes: dict[str, set[int]]) -> list[tuple[int, set[int]]]:
    """Each product named in the text: where the name ends, and which products it names."""
    words = list(re.finditer(r"[a-z0-9]+", folded))
    found: list[tuple[int, set[int]]] = []
    for start in range(len(words)):
        for size in range(1, _CODE_SPAN + 1):
            span = words[start : start + size]
            ids = codes.get("".join(word.group(0) for word in span), set())
            if ids and len(span) == size:
                found.append((span[-1].end(), ids))
    found.sort(key=lambda mention: mention[0])
    return found


def _names_kind(sentence: str, kinds: set[RuleKind]) -> bool:
    folded = fold(sentence)
    words = (word for kind in kinds for word in _KIND_WORDS[kind])
    return any(re.search(rf"\b{re.escape(word)}\b", folded) for word in words)


def _codes(names: dict[int, str]) -> dict[str, set[int]]:
    codes: dict[str, set[int]] = {}
    for product_id, name in names.items():
        for code in code_tokens(name):
            codes.setdefault(code, set()).add(product_id)
    return codes


def _named(sentence: str, codes: dict[str, set[int]]) -> set[int]:
    words = re.findall(r"[a-z0-9]+", fold(sentence))
    named: set[int] = set()
    for start in range(len(words)):
        for size in range(1, _CODE_SPAN + 1):
            joined = "".join(words[start : start + size])
            named.update(codes.get(joined, set()))
    return named
