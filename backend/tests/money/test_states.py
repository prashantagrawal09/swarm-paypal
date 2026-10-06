"""State machines refuse illegal transitions."""

from __future__ import annotations

from itertools import pairwise

import pytest

from app.db.enums import GroupOrderStatus as G
from app.db.enums import ShopOrderStatus as S
from app.money.states import (
    GROUP_ORDER_TRANSITIONS,
    SHOP_ORDER_TRANSITIONS,
    InvalidTransition,
    advance_group_order,
    advance_shop_order,
)


def test_group_order_happy_path():
    path = [
        G.DRAFT,
        G.COLLECTING,
        G.NEGOTIATING,
        G.AWARDED,
        G.HELD,
        G.OUT_FOR_DELIVERY,
        G.DELIVERED,
        G.SETTLED,
    ]
    for current, new in pairwise(path):
        assert advance_group_order(current, new) == new


def test_shop_order_happy_path_and_side_exits():
    assert advance_shop_order(S.PENDING, S.AUTHORIZED) == S.AUTHORIZED
    assert advance_shop_order(S.AUTHORIZED, S.AUTHORIZED) == S.AUTHORIZED  # reauthorization
    assert advance_shop_order(S.AUTHORIZED, S.CAPTURED) == S.CAPTURED
    assert advance_shop_order(S.CAPTURED, S.SETTLED) == S.SETTLED
    assert advance_shop_order(S.SETTLED, S.REFUNDED) == S.REFUNDED
    assert advance_shop_order(S.FAILED, S.PENDING) == S.PENDING


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (G.CANCELLED, G.HELD),
        (G.SETTLED, G.DELIVERED),
        (G.DELIVERED, G.CANCELLED),
        (G.COLLECTING, G.HELD),
    ],
)
def test_group_order_illegal_moves(current, new):
    with pytest.raises(InvalidTransition):
        advance_group_order(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (S.VOIDED, S.AUTHORIZED),
        (S.CAPTURED, S.VOIDED),
        (S.PENDING, S.CAPTURED),
        (S.REFUNDED, S.CAPTURED),
    ],
)
def test_shop_order_illegal_moves(current, new):
    with pytest.raises(InvalidTransition):
        advance_shop_order(current, new)


def test_every_status_has_a_row():
    assert set(GROUP_ORDER_TRANSITIONS) == set(G)
    assert set(SHOP_ORDER_TRANSITIONS) == set(S)
