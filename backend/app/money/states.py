"""State machines for group orders and shop orders (SWARM_SPEC 6.2 and 6.3).

Every status change goes through `advance()`, which refuses transitions that are not in the
tables below, so an order can never jump from, say, CANCELLED back to HELD.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from app.db.enums import GroupOrderStatus as G
from app.db.enums import ShopOrderStatus as S

E = TypeVar("E", bound=StrEnum)

GROUP_ORDER_TRANSITIONS: dict[G, frozenset[G]] = {
    G.DRAFT: frozenset({G.COLLECTING, G.CANCELLED}),
    G.COLLECTING: frozenset({G.NEGOTIATING, G.CANCELLED}),
    G.NEGOTIATING: frozenset({G.AWARDED, G.CANCELLED}),
    G.AWARDED: frozenset({G.HELD, G.CANCELLED}),
    G.HELD: frozenset({G.OUT_FOR_DELIVERY, G.CANCELLED}),
    G.OUT_FOR_DELIVERY: frozenset({G.DELIVERED, G.CANCELLED}),
    G.DELIVERED: frozenset({G.SETTLED, G.PARTIALLY_SETTLED}),
    G.PARTIALLY_SETTLED: frozenset({G.SETTLED}),
    G.SETTLED: frozenset(),
    G.CANCELLED: frozenset(),
}

SHOP_ORDER_TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.AUTHORIZED, S.FAILED, S.VOIDED}),
    # AUTHORIZED -> AUTHORIZED is a reauthorization (new authorization ID).
    S.AUTHORIZED: frozenset({S.AUTHORIZED, S.CAPTURED, S.VOIDED, S.FAILED}),
    S.CAPTURED: frozenset({S.SETTLED, S.REFUNDED}),
    S.SETTLED: frozenset({S.REFUNDED}),
    S.REFUNDED: frozenset({S.REFUNDED}),
    S.FAILED: frozenset({S.PENDING, S.VOIDED}),
    S.VOIDED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, current: StrEnum, new: StrEnum) -> None:
        super().__init__(f"Cannot move from {current} to {new}")
        self.current = current
        self.new = new


def can_transition(current: E, new: E, table: dict[E, frozenset[E]]) -> bool:
    return new in table[current]


def advance(current: E, new: E, table: dict[E, frozenset[E]]) -> E:
    if not can_transition(current, new, table):
        raise InvalidTransition(current, new)
    return new


def advance_group_order(current: G, new: G) -> G:
    return advance(current, new, GROUP_ORDER_TRANSITIONS)


def advance_shop_order(current: S, new: S) -> S:
    return advance(current, new, SHOP_ORDER_TRANSITIONS)


# Shop orders that count against a shop's weekly spending limit.
COMMITTED_SHOP_ORDER_STATUSES = frozenset({S.AUTHORIZED, S.CAPTURED, S.SETTLED, S.REFUNDED})
