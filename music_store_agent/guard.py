"""Reject prices and percents that a tool did not return for that product."""

import re
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from music_store_agent.ledger import Ledger
from music_store_agent.textutil import (
    amounts_in_text,
    code_tokens,
    fold,
    parse_amount,
    percents_in_text,
)

# A sentence ends at ! ? ; a newline, or a period that is not a decimal point.
_BOUNDARY = re.compile(r"[!?;\n]|\.(?!\d)")
_CODE_SPAN = 3


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
) -> GroundingGap:
    """`catalog` maps product ids to names, so a product named without a lookup still counts."""
    amounts = amounts_in_text(message)
    quoted = [quote.amount for quote in quotes]
    missing = [str(amount) for amount in sorted(amounts) if amount not in quoted]
    bad = [_label(q.product_id, q.amount) for q in quotes if not _quote_ok(q, ledger)]
    percents = [str(value) for value in sorted(percents_in_text(message) - ledger.percents)]
    every = amounts | set(quoted)
    unknown = [str(amount) for amount in sorted(every) if not ledger.knows(amount)]
    return GroundingGap(
        tuple(missing),
        tuple(bad),
        tuple(_crossed(message, quotes, {**ledger.names, **(catalog or {})})),
        tuple(percents),
        tuple(unknown),
    )


def _label(product_id: int | None, amount: Decimal) -> str:
    label = "policy" if product_id is None else str(product_id)
    return f"{label}:{amount}"


def _quote_ok(quote: PriceQuote, ledger: Ledger) -> bool:
    if quote.product_id is None:
        return ledger.policy_has(quote.amount)
    return ledger.product_has(quote.product_id, quote.amount)


def _crossed(message: str, quotes: list[PriceQuote], names: dict[int, str]) -> list[str]:
    """A sentence that names products may only carry prices quoted for one of them."""
    owners: dict[Decimal, set[int | None]] = {}
    for quote in quotes:
        owners.setdefault(quote.amount, set()).add(quote.product_id)
    codes = _codes(names)
    crossed: list[str] = []
    for sentence in _BOUNDARY.split(message):
        named = _named(sentence, codes)
        if not named:
            continue
        for amount in sorted(amounts_in_text(sentence)):
            ids = owners.get(amount, set())
            if ids and None not in ids and named.isdisjoint(ids):
                crossed.append(_label(min(i for i in ids if i is not None), amount))
    return crossed


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
