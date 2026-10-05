"""Fixtures for PayPal client tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.clock import SwarmClock
from app.paypal.client import SANDBOX_BASE_URL, PayPalClient
from app.paypal.credentials import PayPalCredentials
from app.paypal.simulated import SimulatedPayPalClient, SimulatedPayPalState

BASE = SANDBOX_BASE_URL


class FakeTime:
    """Controllable monotonic clock plus a sleep that records instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def paypal_mock() -> respx.MockRouter:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.post("/v1/oauth2/token", name="token").respond(
            200, json={"access_token": "TOKEN-1", "token_type": "Bearer", "expires_in": 32400}
        )
        yield router


@pytest.fixture
async def client(paypal_mock, fake_time) -> AsyncIterator[PayPalClient]:
    http = httpx.AsyncClient()
    paypal = PayPalClient(
        PayPalCredentials(client_id="cid", client_secret="secret", label="platform"),
        http=http,
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
    )
    yield paypal
    await http.aclose()


@pytest.fixture
def clock() -> SwarmClock:
    return SwarmClock(datetime(2026, 10, 7, 9, 0, tzinfo=UTC))  # a Wednesday


@pytest.fixture
def sim(clock) -> SimulatedPayPalClient:
    return SimulatedPayPalClient("platform", state=SimulatedPayPalState(), clock=clock)
