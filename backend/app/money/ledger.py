"""Double-entry ledger.

Every money event is written as one transaction group whose debits equal its credits;
`post()` refuses anything else. Balances are `debits - credits` per account.

Accounts (codes, not UUIDs, so the ledger reads like a statement):

| Account                       | Meaning                                                    |
|-------------------------------|------------------------------------------------------------|
| `shop:<code>:paypal`          | The shop's PayPal wallet as seen by Swarm (money in/out)   |
| `shop:<code>:purchases`       | Goods the shop received through Swarm                      |
| `shop:<code>:on_hold`         | Memo: money currently held (authorized, not yet captured)  |
| `shop:<code>:receivable`      | Swarm owes the shop (it sold surplus to a neighbour)       |
| `shop:<code>:sales`           | Surplus the shop sold to neighbours                        |
| `supplier:<code>:payable`     | Swarm owes the supplier for delivered goods                |
| `supplier:<code>:paypal`      | The supplier's PayPal wallet as seen by Swarm              |
| `supplier:<code>:sales`       | What the supplier was paid through Swarm                   |
| `platform:clearing`           | Swarm's PayPal balance holding pass-through money          |
| `platform:fees`               | Swarm's fee income                                         |
| `platform:holds`              | Memo contra-account for all outstanding holds              |

Platform invariant (checked in tests over simulated weeks): what sits in
`platform:clearing` is exactly the fees earned plus what Swarm still owes suppliers and
shops. In signed balances: clearing + fees + payables + receivables == 0.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry

PLATFORM_CLEARING = "platform:clearing"
PLATFORM_FEES = "platform:fees"
PLATFORM_HOLDS = "platform:holds"


def shop_account(code: str, kind: str) -> str:
    return f"shop:{code}:{kind}"


def supplier_account(code: str, kind: str) -> str:
    return f"supplier:{code}:{kind}"


@dataclass(frozen=True)
class Leg:
    account: str
    debit_cents: int = 0
    credit_cents: int = 0


def debit(account: str, cents: int) -> Leg:
    return Leg(account, debit_cents=cents)


def credit(account: str, cents: int) -> Leg:
    return Leg(account, credit_cents=cents)


class UnbalancedTransaction(ValueError):
    pass


def validate_legs(legs: Sequence[Leg]) -> list[Leg]:
    """Drop zero legs, then require a non-empty, one-sided, balanced set."""
    kept = [leg for leg in legs if leg.debit_cents or leg.credit_cents]
    if not kept:
        return []
    for leg in kept:
        if leg.debit_cents < 0 or leg.credit_cents < 0:
            raise UnbalancedTransaction(f"Negative leg on {leg.account}")
        if leg.debit_cents and leg.credit_cents:
            raise UnbalancedTransaction(f"Leg on {leg.account} is both debit and credit")
    debits = sum(leg.debit_cents for leg in kept)
    credits = sum(leg.credit_cents for leg in kept)
    if debits != credits:
        raise UnbalancedTransaction(f"Debits {debits} != credits {credits}")
    return kept


async def post(
    session: AsyncSession,
    *,
    event: str,
    memo: str,
    legs: Sequence[Leg],
    currency: str,
    booked_at: datetime,
    related_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Write one balanced transaction group. Returns its ID (None if every leg was zero)."""
    kept = validate_legs(legs)
    if not kept:
        return None
    txn = uuid.uuid4()
    for leg in kept:
        session.add(
            LedgerEntry(
                txn_group_id=txn,
                account=leg.account,
                debit_cents=leg.debit_cents,
                credit_cents=leg.credit_cents,
                currency=currency,
                memo=memo[:255],
                event=event,
                related_id=related_id,
                booked_at=booked_at,
            )
        )
    await session.flush()
    return txn


# ---------------------------------------------------------------------------------------
# Postings for each money event (pure: they only build legs)
# ---------------------------------------------------------------------------------------


def hold_placed(shop: str, cents: int) -> list[Leg]:
    return [debit(shop_account(shop, "on_hold"), cents), credit(PLATFORM_HOLDS, cents)]


def hold_released(shop: str, cents: int) -> list[Leg]:
    return [debit(PLATFORM_HOLDS, cents), credit(shop_account(shop, "on_hold"), cents)]


def captured_for_supplier(shop: str, supplier: str, cents: int) -> list[Leg]:
    """Shop paid the platform; the platform now owes the supplier for the goods."""
    return [
        debit(PLATFORM_CLEARING, cents),
        credit(shop_account(shop, "paypal"), cents),
        debit(shop_account(shop, "purchases"), cents),
        credit(supplier_account(supplier, "payable"), cents),
    ]


def refunded_by_supplier(shop: str, supplier: str, cents: int) -> list[Leg]:
    """Money back to the shop; the supplier is owed that much less."""
    return [
        debit(shop_account(shop, "paypal"), cents),
        credit(PLATFORM_CLEARING, cents),
        debit(supplier_account(supplier, "payable"), cents),
        credit(shop_account(shop, "purchases"), cents),
    ]


def supplier_paid_out(supplier: str, gross_cents: int, fee_cents: int) -> list[Leg]:
    net = gross_cents - fee_cents
    return [
        debit(supplier_account(supplier, "payable"), gross_cents),
        credit(PLATFORM_CLEARING, net),
        credit(PLATFORM_FEES, fee_cents),
        debit(supplier_account(supplier, "paypal"), net),
        credit(supplier_account(supplier, "sales"), net),
    ]


def swap_captured(buyer: str, seller: str, cents: int) -> list[Leg]:
    return [
        debit(PLATFORM_CLEARING, cents),
        credit(shop_account(buyer, "paypal"), cents),
        debit(shop_account(buyer, "purchases"), cents),
        credit(shop_account(seller, "receivable"), cents),
    ]


def swap_paid_out(seller: str, cents: int) -> list[Leg]:
    return [
        debit(shop_account(seller, "receivable"), cents),
        credit(PLATFORM_CLEARING, cents),
        debit(shop_account(seller, "paypal"), cents),
        credit(shop_account(seller, "sales"), cents),
    ]


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


async def balance(session: AsyncSession, account: str) -> int:
    result = await session.execute(
        select(
            func.coalesce(func.sum(LedgerEntry.debit_cents), 0)
            - func.coalesce(func.sum(LedgerEntry.credit_cents), 0)
        ).where(LedgerEntry.account == account)
    )
    return int(result.scalar_one())


async def balances(session: AsyncSession, prefix: str = "") -> dict[str, int]:
    result = await session.execute(
        select(
            LedgerEntry.account,
            func.sum(LedgerEntry.debit_cents) - func.sum(LedgerEntry.credit_cents),
        )
        .where(LedgerEntry.account.startswith(prefix))
        .group_by(LedgerEntry.account)
    )
    return {account: int(total) for account, total in result.all()}


async def unbalanced_transactions(session: AsyncSession) -> list[uuid.UUID]:
    result = await session.execute(
        select(LedgerEntry.txn_group_id)
        .group_by(LedgerEntry.txn_group_id)
        .having(func.sum(LedgerEntry.debit_cents) != func.sum(LedgerEntry.credit_cents))
    )
    return list(result.scalars())


async def platform_invariant_gap(session: AsyncSession) -> int:
    """clearing + fees + supplier payables + shop receivables. Must be 0."""
    all_balances = await balances(session)
    return sum(
        value
        for account, value in all_balances.items()
        if account in (PLATFORM_CLEARING, PLATFORM_FEES)
        or account.endswith(":payable")
        or account.endswith(":receivable")
    )
