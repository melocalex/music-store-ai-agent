"""Order identity is full contact, the attempt limit holds, and history is not recomputed."""

import re
from dataclasses import replace
from datetime import date, timedelta

from music_store_agent.constants import (
    ASK_CONTACT,
    ASK_PHONE,
    DEFECT_EXCHANGE_DAYS,
    LEGAL_WARRANTY_DAYS,
    MAX_VERIFICATION_ATTEMPTS,
    NOT_VERIFIED,
    NOT_YOUR_ORDER,
    PREFERENCE_DAYS,
    REGRET_DAYS,
    UNESTIMATED_ORDER_DAYS,
    VERIFICATION_FAILED,
    VERIFICATION_LOCKED,
)
from music_store_agent.db import load_database
from music_store_agent.ledger import Ledger
from music_store_agent.orders import (
    Identity,
    defect_line,
    explain_after_sales,
    is_late,
    is_stale,
    load_order,
    preference_line,
    read_order,
    receipt_line,
    verify,
)

TODAY = date(2026, 3, 23)
LUCAS_EMAIL = "lucas.mendes@jmail.com"
LUCAS_PHONE = "(67) 99812-3456"
ISABELA_EMAIL = "isabela.moreira@jmail.com"
SHARED_EMAIL = "bruno.martins@jmail.com"
BRUNO_11_PHONE = "(67) 98543-2109"
BRUNO_43_PHONE = "(67) 99456-3456"
WRONG_EMAIL = "outra.pessoa@jmail.com"


def test_wrong_owner_and_attempt_limit() -> None:
    conn = load_database()
    identity = Identity()
    for _ in range(MAX_VERIFICATION_ATTEMPTS - 1):
        assert verify(identity, conn, 4, WRONG_EMAIL, None) == VERIFICATION_FAILED
    assert verify(identity, conn, 4, WRONG_EMAIL, None) == VERIFICATION_LOCKED
    assert identity.locked
    assert verify(identity, conn, 4, LUCAS_EMAIL, None) == VERIFICATION_LOCKED
    assert identity.verified_customer_id is None


def test_last_allowed_attempt_still_succeeds() -> None:
    conn = load_database()
    identity = Identity()
    for _ in range(MAX_VERIFICATION_ATTEMPTS - 1):
        verify(identity, conn, 4, WRONG_EMAIL, None)
    assert "Lucas" in verify(identity, conn, 4, LUCAS_EMAIL, None)
    assert not identity.locked


def test_a_success_does_not_reset_the_failure_count() -> None:
    conn = load_database()
    identity = Identity()
    for _ in range(MAX_VERIFICATION_ATTEMPTS - 1):
        verify(identity, conn, 1, WRONG_EMAIL, None)
    assert "Lucas" in verify(identity, conn, 4, LUCAS_EMAIL, None)
    assert verify(identity, conn, 1, WRONG_EMAIL, None) == VERIFICATION_LOCKED


def test_either_full_credential_works_and_the_sender_phone_adds_a_way() -> None:
    conn = load_database()
    by_phone = Identity()
    assert "Lucas" in verify(by_phone, conn, 4, None, "+55 67 99812-3456")
    stranger_sender = Identity(sender_phone="(67) 99999-0000")
    assert "Lucas" in verify(stranger_sender, conn, 4, LUCAS_EMAIL, None)
    owner_sender = Identity(sender_phone=LUCAS_PHONE)
    assert "Lucas" in verify(owner_sender, conn, 4, None, None)
    nobody = Identity()
    assert verify(nobody, conn, 4, None, None) == ASK_CONTACT
    assert nobody.failed_verifications == 0


def test_shared_email_needs_the_phone_of_that_order() -> None:
    conn = load_database()
    identity = Identity()
    assert verify(identity, conn, 10, SHARED_EMAIL, None) == ASK_PHONE
    assert identity.verified_customer_id is None
    assert identity.failed_verifications == 0
    assert verify(identity, conn, 10, SHARED_EMAIL, BRUNO_43_PHONE) == VERIFICATION_FAILED
    assert "Bruno" in verify(identity, conn, 10, SHARED_EMAIL, BRUNO_11_PHONE)
    assert identity.verified_customer_id == 11
    assert read_order(identity, conn, 1, TODAY, Ledger()) == NOT_YOUR_ORDER


def test_a_shared_email_with_another_sender_phone_asks_for_the_phone() -> None:
    conn = load_database()
    identity = Identity(sender_phone=LUCAS_PHONE)
    assert verify(identity, conn, 10, SHARED_EMAIL, None) == ASK_PHONE
    assert identity.failed_verifications == 0
    assert verify(identity, conn, 10, SHARED_EMAIL, BRUNO_43_PHONE) == VERIFICATION_FAILED
    assert identity.failed_verifications == 1
    owner = Identity(sender_phone=BRUNO_11_PHONE)
    assert "Bruno" in verify(owner, conn, 10, SHARED_EMAIL, None)


def test_order_tools_refuse_before_verification() -> None:
    conn = load_database()
    identity = Identity()
    assert read_order(identity, conn, 4, TODAY, Ledger()) == NOT_VERIFIED
    result = explain_after_sales(identity, conn, 4, TODAY)
    assert result.text == NOT_VERIFIED
    assert not result.open_to_request


def test_stored_total_items_and_labels() -> None:
    conn = load_database()
    identity = Identity()
    verify(identity, conn, 3, ISABELA_EMAIL, None)
    ledger = Ledger()
    text = read_order(identity, conn, 3, TODAY, ledger)
    assert "3450.00" in text
    assert "3498" not in text
    assert re.search(r"Itens: \d+x ", text)
    assert "entregue" in text or "enviado" in text or "confirmado" in text
    assert ledger.policy_has(load_order(conn, 3).pay.total)
    assert read_order(identity, conn, 1, TODAY, Ledger()) == NOT_YOUR_ORDER


def test_a_cancelled_order_shows_its_stored_reason() -> None:
    conn = load_database()
    identity = Identity()
    order = load_order(conn, 19)
    assert order.pay.status == "cancelled"
    verify(identity, conn, 19, order.buyer.email, None)
    text = read_order(identity, conn, 19, TODAY, Ledger())
    assert f"Motivo do cancelamento gravado: {order.ship.notes}." in text
    assert "observação operacional" not in text


def test_defect_window_is_inclusive_on_day_thirty() -> None:
    bought = date(2026, 1, 1)
    inside = defect_line(bought, bought + timedelta(days=DEFECT_EXCHANGE_DAYS), True)
    outside = defect_line(bought, bought + timedelta(days=DEFECT_EXCHANGE_DAYS + 1), True)
    assert "dentro do prazo" in inside
    assert "fora do prazo" in outside


def test_receipt_windows_use_the_purchase_as_a_lower_bound() -> None:
    bought = date(2026, 1, 1)
    open_day = bought + timedelta(days=LEGAL_WARRANTY_DAYS)
    late_day = bought + timedelta(days=LEGAL_WARRANTY_DAYS + 1)
    still_open = receipt_line("Garantia", LEGAL_WARRANTY_DAYS, bought, open_day, True)
    assert "ainda está aberto" in still_open
    unsure = receipt_line("Garantia", LEGAL_WARRANTY_DAYS, bought, late_day, True)
    assert "Peça essa data" in unsure
    waiting = receipt_line("Arrependimento", REGRET_DAYS, bought, late_day, False)
    assert "não começou" in waiting


def test_order_seven_states_the_windows() -> None:
    conn = load_database()
    identity = Identity()
    order = load_order(conn, 7)
    verify(identity, conn, 7, order.buyer.email, None)
    result = explain_after_sales(identity, conn, 7, TODAY)
    elapsed = (TODAY - order.ship.ordered_on).days
    assert DEFECT_EXCHANGE_DAYS < elapsed <= LEGAL_WARRANTY_DAYS
    assert "fora do prazo" in result.text
    assert f"Garantia legal: {LEGAL_WARRANTY_DAYS} dias do recebimento. A compra foi" in result.text
    assert "ainda está aberto" in result.text
    assert "Não aprovo" in result.text
    assert result.open_to_request


def test_an_order_still_on_its_way_has_no_exchange_window_yet() -> None:
    conn = load_database()
    identity = Identity()
    order = load_order(conn, 8)
    assert order.pay.status == "shipped" and is_late(order, TODAY)
    verify(identity, conn, 8, order.buyer.email, None)
    text = explain_after_sales(identity, conn, 8, TODAY).text
    assert "fora do prazo" not in text
    assert "Peça a data de recebimento" not in text
    assert "Peça essa data" not in text
    defect, preference = (
        line
        for line in text.splitlines()
        if line.startswith(("Troca por defeito", "Troca por pref"))
    )
    assert "ainda não foi entregue" in defect
    assert "ainda não foi entregue" in preference


def test_late_starts_the_day_after_the_estimate() -> None:
    conn = load_database()
    order = load_order(conn, 8)
    estimate = order.ship.estimate
    assert not is_late(order, estimate)
    assert is_late(order, estimate + timedelta(days=1))
    delivered = replace(order, pay=replace(order.pay, status="delivered"))
    assert not is_late(delivered, estimate + timedelta(days=1))


def test_an_open_order_with_no_estimate_is_flagged_once_it_is_old() -> None:
    conn = load_database()
    order = load_order(conn, 9)
    assert order.ship.estimate is None and order.pay.status == "confirmed"
    limit = order.ship.ordered_on + timedelta(days=UNESTIMATED_ORDER_DAYS)
    assert not is_stale(order, limit)
    assert is_stale(order, limit + timedelta(days=1))
    identity = Identity()
    verify(identity, conn, 9, order.buyer.email, None)
    text = read_order(identity, conn, 9, TODAY, Ledger())
    assert "não tem estimativa de entrega gravada" in text
    recent = load_order(conn, 12)
    assert recent.ship.estimate is None
    assert not is_stale(recent, TODAY)
    done = replace(order, pay=replace(order.pay, status="delivered"))
    assert not is_stale(done, TODAY)


def test_preference_window_states_that_its_start_is_unclear() -> None:
    bought = date(2026, 1, 1)
    inside = preference_line(bought, bought + timedelta(days=PREFERENCE_DAYS), True)
    after = preference_line(bought, bought + timedelta(days=PREFERENCE_DAYS + 1), True)
    assert "nas duas leituras" in inside
    assert "Peça a data de recebimento" in after
    assert "não diz se contam da compra ou do recebimento" in inside
