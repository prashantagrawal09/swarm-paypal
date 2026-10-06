"""Every posting template balances; the validator rejects bad legs."""

from __future__ import annotations

import pytest

from app.money import ledger


@pytest.mark.parametrize(
    "legs",
    [
        ledger.hold_placed("cafe-mei", 1000),
        ledger.hold_released("cafe-mei", 1000),
        ledger.captured_for_supplier("cafe-mei", "freshdairy", 900),
        ledger.refunded_by_supplier("cafe-mei", "freshdairy", 100),
        ledger.supplier_paid_out("freshdairy", 900, 18),
        ledger.swap_captured("teh-time", "cafe-mei", 1200),
        ledger.swap_paid_out("cafe-mei", 1200),
    ],
)
def test_templates_balance(legs):
    assert ledger.validate_legs(legs)


def test_validator_rejects_unbalanced_and_mixed_legs():
    with pytest.raises(ledger.UnbalancedTransaction):
        ledger.validate_legs([ledger.debit("a", 10), ledger.credit("b", 9)])
    with pytest.raises(ledger.UnbalancedTransaction):
        ledger.validate_legs([ledger.Leg("a", 5, 5)])
    with pytest.raises(ledger.UnbalancedTransaction):
        ledger.validate_legs([ledger.Leg("a", -5, 0), ledger.credit("b", -5)])
    assert ledger.validate_legs([ledger.debit("a", 0), ledger.credit("b", 0)]) == []


def test_platform_invariant_holds_for_a_full_cycle():
    """capture -> refund -> payout leaves clearing == fees + nothing owed."""
    legs = (
        ledger.captured_for_supplier("s1", "sup", 1000)
        + ledger.refunded_by_supplier("s1", "sup", 100)
        + ledger.supplier_paid_out("sup", 900, 18)
    )
    totals: dict[str, int] = {}
    for leg in legs:
        totals[leg.account] = totals.get(leg.account, 0) + leg.debit_cents - leg.credit_cents
    assert totals[ledger.PLATFORM_CLEARING] == 18
    assert totals[ledger.PLATFORM_FEES] == -18
    assert totals["supplier:sup:payable"] == 0
