"""Reject prices that a tool did not return for that product."""

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from music_store_agent.ledger import Ledger
from music_store_agent.textutil import amounts_in_text, parse_amount


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

    @property
    def ok(self) -> bool:
        return not self.message_amounts and not self.bad_quotes


def grounding_gap(message: str, quotes: list[PriceQuote], ledger: Ledger) -> GroundingGap:
    quoted = [quote.amount for quote in quotes]
    missing = [str(amount) for amount in sorted(amounts_in_text(message)) if amount not in quoted]
    bad = [_bad_label(quote) for quote in quotes if not _quote_ok(quote, ledger)]
    return GroundingGap(tuple(missing), tuple(bad))


def _bad_label(quote: PriceQuote) -> str:
    label = "policy" if quote.product_id is None else str(quote.product_id)
    return f"{label}:{quote.amount}"


def _quote_ok(quote: PriceQuote, ledger: Ledger) -> bool:
    if quote.product_id is None:
        return ledger.policy_has(quote.amount) and not _owned_by_product(quote.amount, ledger)
    return ledger.product_has(quote.product_id, quote.amount)


def _owned_by_product(amount: Decimal, ledger: Ledger) -> bool:
    return any(amount in bucket for bucket in ledger.by_product.values())

