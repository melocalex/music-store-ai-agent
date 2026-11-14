"""Amounts a tool actually returned.

A product price, a line total, or an installment sits under the product it belongs to.
A rule value, such as freight, a floor, or a stored order total, sits in the rule map with its
kind, so a reply can only cite it as that kind of value. The customer's own budget, echoed by the
search, is kept apart: it is not a store value at all.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from music_store_agent.constants import (
    CENT,
    FREIGHT_FLAT,
    FREIGHT_FREE_FROM,
    MIN_PARCEL_2_TO_3,
    MIN_PARCEL_4_TO_6,
    MIN_PARCEL_7_TO_12,
    SPLIT_PAYMENT_ABOVE,
)

RuleKind = Literal["freight", "floor", "threshold", "order_total", "budget", "rule"]
FREIGHT: RuleKind = "freight"
FLOOR: RuleKind = "floor"
THRESHOLD: RuleKind = "threshold"
ORDER_TOTAL: RuleKind = "order_total"
BUDGET: RuleKind = "budget"
RULE: RuleKind = "rule"

# The manual's amounts are these constants, which a manual check keeps in step.
_MANUAL_KINDS: dict[Decimal, RuleKind] = {
    FREIGHT_FLAT: FREIGHT,
    FREIGHT_FREE_FROM: FREIGHT,
    MIN_PARCEL_2_TO_3: FLOOR,
    MIN_PARCEL_4_TO_6: FLOOR,
    MIN_PARCEL_7_TO_12: FLOOR,
    SPLIT_PAYMENT_ABOVE: THRESHOLD,
}


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT)


def manual_kind(amount: Decimal) -> RuleKind:
    """The kind of an amount read from a manual section."""
    return _MANUAL_KINDS.get(_cents(amount), RULE)


@dataclass
class Ledger:
    by_product: dict[int, set[Decimal]] = field(default_factory=dict)
    policy: dict[Decimal, set[RuleKind]] = field(default_factory=dict)
    budgets: set[Decimal] = field(default_factory=set)
    names: dict[int, str] = field(default_factory=dict)
    percents: set[Decimal] = field(default_factory=set)

    def add_product(self, product_id: int, amount: Decimal, name: str = "") -> None:
        bucket = self.by_product.setdefault(product_id, set())
        bucket.add(_cents(amount))
        if name:
            self.names[product_id] = name

    def add_policy(self, amount: Decimal, kind: RuleKind) -> None:
        self.policy.setdefault(_cents(amount), set()).add(kind)

    def add_budget(self, amount: Decimal) -> None:
        self.budgets.add(_cents(amount))

    def add_percents(self, percents: set[Decimal]) -> None:
        self.percents.update(_cents(percent) for percent in percents)

    def product_has(self, product_id: int, amount: Decimal) -> bool:
        return _cents(amount) in self.by_product.get(product_id, set())

    def policy_has(self, amount: Decimal) -> bool:
        """A null-id quote may cite a rule value or the customer's budget."""
        cents = _cents(amount)
        return cents in self.policy or cents in self.budgets

    def rule_kinds(self, amount: Decimal) -> set[RuleKind]:
        cents = _cents(amount)
        kinds = set(self.policy.get(cents, set()))
        if cents in self.budgets:
            kinds.add(BUDGET)
        return kinds

    def knows(self, amount: Decimal) -> bool:
        cents = _cents(amount)
        return self.policy_has(cents) or any(cents in bucket for bucket in self.by_product.values())
