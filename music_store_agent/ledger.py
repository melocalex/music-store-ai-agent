"""Amounts a tool actually returned.

A product price, a line total, or an installment sits under the product it belongs to.
A rule value, such as freight, a floor, or a stored order total, sits in the policy set.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from music_store_agent.constants import CENT


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT)


@dataclass
class Ledger:
    by_product: dict[int, set[Decimal]] = field(default_factory=dict)
    policy: set[Decimal] = field(default_factory=set)
    names: dict[int, str] = field(default_factory=dict)
    percents: set[Decimal] = field(default_factory=set)

    def add_product(self, product_id: int, amount: Decimal, name: str = "") -> None:
        bucket = self.by_product.setdefault(product_id, set())
        bucket.add(_cents(amount))
        if name:
            self.names[product_id] = name

    def add_policy(self, amount: Decimal) -> None:
        self.policy.add(_cents(amount))

    def add_percents(self, percents: set[Decimal]) -> None:
        self.percents.update(_cents(percent) for percent in percents)

    def product_has(self, product_id: int, amount: Decimal) -> bool:
        return _cents(amount) in self.by_product.get(product_id, set())

    def policy_has(self, amount: Decimal) -> bool:
        return _cents(amount) in self.policy

    def knows(self, amount: Decimal) -> bool:
        cents = _cents(amount)
        return cents in self.policy or any(cents in bucket for bucket in self.by_product.values())
