"""Amounts a tool actually returned, keyed by product when the figure is a price."""

from dataclasses import dataclass, field
from decimal import Decimal

from music_store_agent.constants import CENT


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT)


@dataclass
class Ledger:
    by_product: dict[int, set[Decimal]] = field(default_factory=dict)
    policy: set[Decimal] = field(default_factory=set)

    def add_product(self, product_id: int, amount: Decimal) -> None:
        bucket = self.by_product.setdefault(product_id, set())
        bucket.add(_cents(amount))

    def add_policy(self, amount: Decimal) -> None:
        self.policy.add(_cents(amount))

    def product_has(self, product_id: int, amount: Decimal) -> bool:
        return _cents(amount) in self.by_product.get(product_id, set())

    def policy_has(self, amount: Decimal) -> bool:
        return _cents(amount) in self.policy
