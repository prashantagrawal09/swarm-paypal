"""Connect PayPal: the one-time approval that lets a shop's agent place holds later.

The owner approves a S$1.00 check on PayPal with "save PayPal for future purchases" (vault).
Swarm authorizes it, keeps the vault ID on the shop, and voids the S$1.00 straight away, so
nothing is charged. Simulated shops go through the same steps against the simulator, with
an in-app approval screen standing in for PayPal's.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

from app.db.app_state import get_state, set_state
from app.db.enums import PayPalModeEnum
from app.db.models import AuditLog
from app.features.context import Ctx
from app.money.amount import Money
from app.paypal.errors import PayPalError
from app.paypal.interface import CreateOrderRequest
from app.paypal.simulated import SimulatedPayPalClient

CHECK_CENTS = 100


async def start(ctx: Ctx, shop_code: str, link_token: str | None = None) -> dict[str, Any]:
    """Creates the S$1.00 check order. `link_token` (the owner's signed link) rides along on
    the return URL so the page PayPal sends the owner back to can finish the job."""
    shop = await ctx.shop(shop_code)
    gateway = ctx.runtime.registry.platform(shop.paypal_mode.value)
    frontend = ctx.runtime.settings.public_frontend_url.rstrip("/")
    page = f"{frontend}/connect/{shop.code}"
    signed = f"t={quote(link_token)}&" if link_token else ""
    order = await gateway.create_order(
        CreateOrderRequest(
            amount=Money(CHECK_CENTS, shop.currency),
            reference_id=f"connect-{shop.code}"[:60],
            description="Swarm: connect your PayPal (S$1.00 check, released straight away)",
            save_payment_method=True,
            return_url=f"{page}?{signed}".rstrip("?&"),
            cancel_url=f"{page}?{signed}cancelled=1",
        ),
        idempotency_key=f"connect:{shop.id.hex}:{uuid.uuid4().hex[:10]}",
    )
    approve_url = order.approve_url
    if shop.paypal_mode == PayPalModeEnum.SIMULATED:
        approve_url = f"{page}?{signed}sim_order={order.id}"
    await set_state(
        ctx.session, f"connect:{shop.code}", {"order_id": order.id, "mode": shop.paypal_mode.value}
    )
    await ctx.session.commit()
    return {"mode": shop.paypal_mode.value, "order_id": order.id, "approve_url": approve_url}


async def simulated_approve(ctx: Ctx, shop_code: str, order_id: str) -> None:
    shop = await ctx.shop(shop_code)
    gateway = ctx.runtime.registry.platform("SIMULATED")
    if not isinstance(gateway, SimulatedPayPalClient):
        raise ValueError("Not a simulated shop")
    gateway.approve_order(order_id, shop.paypal_email or f"{shop.code}@sim.swarm.example")


async def complete(ctx: Ctx, shop_code: str, order_id: str) -> dict[str, Any]:
    shop = await ctx.shop(shop_code)
    pending = await get_state(ctx.session, f"connect:{shop.code}") or {}
    if pending.get("order_id") != order_id:
        raise ValueError("That approval doesn't match this shop. Start again.")
    gateway = ctx.runtime.registry.platform(shop.paypal_mode.value)
    order = await gateway.authorize_order(order_id, idempotency_key=f"connect-auth:{order_id}")
    if order.vault is None or not order.vault.id:
        raise PayPalError(
            "PayPal approved the check but did not save the wallet. "
            "Enable Vault on the PayPal app (see docs/paypal-setup.md)."
        )
    shop.vault_id = order.vault.id
    if order.payer_email and shop.paypal_mode == PayPalModeEnum.REAL:
        shop.paypal_email = order.payer_email
    if order.authorization is not None:
        await gateway.void_authorization(
            order.authorization.id, idempotency_key=f"connect-void:{order.authorization.id}"
        )
    ctx.session.add(
        AuditLog(
            actor=f"owner:{shop.code}",
            action="paypal_connected",
            details={"mode": shop.paypal_mode.value, "order_id": order_id},
            created_at=ctx.now(),
        )
    )
    await set_state(ctx.session, f"connect:{shop.code}", {})
    await ctx.session.commit()
    await ctx.say_to_owner(
        shop,
        "✅ PayPal connected. I can now hold money for group orders without you logging "
        "in. Nothing is charged until your delivery arrives.",
        kind="CONNECTED",
    )
    return {"connected": True, "vault_tail": shop.vault_id[-6:], "payer_email": order.payer_email}
