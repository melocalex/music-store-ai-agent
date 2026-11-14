"""Order identity is full contact, and history is not recomputed."""

from datetime import date

from music_store_agent.constants import (
    DEFECT_EXCHANGE_DAYS,
    LEGAL_WARRANTY_DAYS,
    MAX_VERIFICATION_ATTEMPTS,
    NOT_YOUR_ORDER,
    VERIFICATION_FAILED,
    VERIFICATION_LOCKED,
)
from music_store_agent.db import load_database
from music_store_agent.ledger import Ledger
from music_store_agent.orders import Identity, explain_after_sales, load_orders, read_order, verify

TODAY = date(2026, 3, 23)
LUCAS_EMAIL = "lucas.mendes@jmail.com"
LUCAS_PHONE = "(67) 99812-3456"
ISABELA_EMAIL = "isabela.moreira@jmail.com"
BRUNO_EMAIL = "bruno.martins@jmail.com"


def _orders():
    return load_orders(load_database())


def test_wrong_owner_and_attempt_limit() -> None:
    orders = _orders()
    identity = Identity()
    for _ in range(MAX_VERIFICATION_ATTEMPTS - 1):
        text = verify(identity, orders, 4, "outra.pessoa@jmail.com", None)
        assert text == VERIFICATION_FAILED
    locked = verify(identity, orders, 4, "outra.pessoa@jmail.com", None)
    assert locked == VERIFICATION_LOCKED
    assert identity.locked


def test_full_phone_and_sender_override() -> None:
    orders = _orders()
    identity = Identity()
    text = verify(identity, orders, 4, None, "+55 67 99812-3456")
    assert "Lucas" in text
    assert identity.verified_customer_id == orders[4].customer_id
    other = Identity(sender_phone="(67) 99999-0000")
    refused = verify(other, orders, 4, LUCAS_EMAIL, LUCAS_PHONE)
    assert refused == VERIFICATION_FAILED


def test_duplicate_email_is_order_scoped() -> None:
    orders = _orders()
    identity = Identity()
    text = verify(identity, orders, 10, BRUNO_EMAIL, None)
    assert identity.verified_customer_id == 11
    assert "confirmado" in text
    denied = read_order(identity, orders, 1, TODAY, Ledger())
    assert denied == NOT_YOUR_ORDER


def test_stored_total_and_other_order_tracking() -> None:
    orders = _orders()
    identity = Identity()
    verify(identity, orders, 3, ISABELA_EMAIL, None)
    ledger = Ledger()
    text = read_order(identity, orders, 3, TODAY, ledger)
    assert "3450.00" in text
    assert "3498" not in text
    assert read_order(identity, orders, 1, TODAY, Ledger()) == NOT_YOUR_ORDER


def test_order_seven_states_both_windows() -> None:
    orders = _orders()
    identity = Identity()
    verify(identity, orders, 7, orders[7].buyer.email, None)
    text = explain_after_sales(identity, orders, 7, TODAY)
    assert str(DEFECT_EXCHANGE_DAYS) in text
    assert str(LEGAL_WARRANTY_DAYS) in text
    assert "fora do prazo" in text
    assert "Não aprovo" in text
    assert "2026-02-17" not in text or "recebimento" in text
