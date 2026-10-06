"""The simulated PayPal survives a restart through its JSON snapshot."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.money.amount import Money
from app.paypal.interface import CreateOrderRequest, InvoiceDraft, InvoiceLine, PayoutItemRequest
from app.paypal.simulated import SimulatedPayPalClient, SimulatedPayPalState


async def test_snapshot_round_trip_keeps_money_rules_and_idempotency(sim, clock):
    sim.register_vault("SIM-VAULT-X", "x@sim.example")
    order = await sim.create_order(
        CreateOrderRequest(amount=Money(1000), reference_id="r", vault_id="SIM-VAULT-X"),
        idempotency_key="o1",
    )
    auth_id = order.authorization.id
    capture = await sim.capture_authorization(
        auth_id, amount=Money(400), final_capture=False, idempotency_key="c1"
    )
    await sim.create_payout(
        sender_batch_id="b1",
        items=[PayoutItemRequest("s@x", Money(100), "i1")],
        idempotency_key="p1",
        email_subject="s",
    )
    await sim.create_invoice(
        InvoiceDraft(
            "N-1", date(2026, 10, 1), "SGD", "p@x", [InvoiceLine("Milk", Decimal(2), Money(205))]
        ),
        idempotency_key="i1",
    )

    restored_state = SimulatedPayPalState.from_dict(json.loads(json.dumps(sim.state.to_dict())))
    restored = SimulatedPayPalClient("platform", state=restored_state, clock=clock)
    assert restored_state.next_number == sim.state.next_number

    replay = await restored.capture_authorization(
        auth_id, amount=Money(400), final_capture=False, idempotency_key="c1"
    )
    assert replay == capture
    rest = await restored.capture_authorization(
        auth_id, amount=Money(600), final_capture=True, idempotency_key="c2"
    )
    assert rest.amount == Money(600)
    assert (await restored.get_authorization(auth_id)).status == "CAPTURED"


async def test_on_change_is_called_after_each_mutation(clock):
    snapshots = []

    async def keep(state: SimulatedPayPalState) -> None:
        snapshots.append(state.to_dict())

    client = SimulatedPayPalClient("platform", clock=clock, on_change=keep)
    client.register_vault("V", "v@x")
    await client.create_order(
        CreateOrderRequest(amount=Money(100), reference_id="r", vault_id="V"), idempotency_key="k"
    )
    await client.create_order(
        CreateOrderRequest(amount=Money(100), reference_id="r", vault_id="V"), idempotency_key="k"
    )
    assert len(snapshots) == 1  # the replay changed nothing
