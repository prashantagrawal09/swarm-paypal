"""Claims agent: looks at the owner's photo, then code decides the refund.

1. The model (with vision) assesses the evidence: what the photo shows, how many units are
   affected, and how confident it is. It never estimates money.
2. Code decides (`decide`):
   - refund amount = affected units (the smallest of: the model's count, the owner's count,
     what was delivered) x the agreed unit price;
   - confident (>= 0.8), supported, small (<= S$50) and matching the claim type: refund now
     through PayPal;
   - supported but bigger or less certain: ask the supplier;
   - unclear evidence: the platform operator decides;
   - confidently contradicted by the photo: rejected.
Without a photo, or without a model to read it, the claim always goes to a person; nothing is
refunded automatically. While a person is deciding, the amount at stake is what the owner
claimed (never more than was delivered), so that much is held back from the supplier's payout.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Action, Agent, Verdict
from app.agents.bus import MessageBus
from app.agents.prompting import wrap_untrusted
from app.clock import Clock
from app.db.enums import ClaimDecision, ClaimType
from app.db.models import Claim, GroupOrderLine, Shop, ShopOrder
from app.llm.client import LLM, Content
from app.money.amount import Money
from app.money.engine import MoneyEngine

AUTO_REFUND_LIMIT_CENTS = 5000
MIN_CONFIDENCE = 0.8
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


class ClaimAssessment(BaseModel):
    issue_type: Literal["SHORT", "DAMAGED", "EXPIRED", "WRONG_ITEM", "NONE", "UNCLEAR"]
    claim_supported: bool
    confidence: float
    qty_affected: int
    evidence: str


@dataclass(frozen=True)
class ClaimOutcome:
    decision: ClaimDecision
    refund_cents: int
    qty: int
    reason: str


NO_PHOTO = "No photo came with this claim, so a person will check."
NOT_REVIEWED = "The photo couldn't be checked automatically, so a person will check."


def decide(
    claim: Claim, line: GroupOrderLine, assessment: ClaimAssessment, *, reviewed: bool = True
) -> ClaimOutcome:
    """`reviewed` is False when nothing looked at a photo (none sent, or no model to read it)."""
    delivered = line.qty_delivered if line.qty_delivered is not None else line.qty_requested
    price = line.agreed_unit_price_cents or 0
    claimed = max(0, min(claim.qty_affected or delivered, delivered))
    qty = max(0, min(assessment.qty_affected, claimed))
    refund = qty * price
    # What a person rules on when the photo settles nothing: the owner's own count.
    at_stake = claimed * price
    confidence = max(0.0, min(1.0, assessment.confidence))
    matches = assessment.issue_type == claim.type.value
    if not reviewed:
        return ClaimOutcome(
            ClaimDecision.ESCALATED_OPERATOR,
            at_stake,
            claimed,
            NOT_REVIEWED if claim.photo_url else NO_PHOTO,
        )
    if assessment.issue_type == "UNCLEAR" or confidence < 0.5:
        return ClaimOutcome(
            ClaimDecision.ESCALATED_OPERATOR,
            at_stake,
            claimed,
            "The photo doesn't clearly show the problem; a person will check.",
        )
    if not assessment.claim_supported or assessment.issue_type == "NONE":
        if confidence >= MIN_CONFIDENCE:
            return ClaimOutcome(
                ClaimDecision.REJECTED, 0, 0, "The photo doesn't show the problem described."
            )
        return ClaimOutcome(
            ClaimDecision.ESCALATED_OPERATOR,
            at_stake,
            claimed,
            "Mixed evidence; a person will check.",
        )
    if qty == 0:
        return ClaimOutcome(
            ClaimDecision.ESCALATED_SUPPLIER,
            at_stake,
            claimed,
            "Problem confirmed but no units could be counted; asking the supplier.",
        )
    if confidence >= MIN_CONFIDENCE and matches and refund <= AUTO_REFUND_LIMIT_CENTS:
        return ClaimOutcome(
            ClaimDecision.AUTO_REFUNDED,
            refund,
            qty,
            f"Clear evidence for {qty} unit(s); refunded automatically.",
        )
    return ClaimOutcome(
        ClaimDecision.ESCALATED_SUPPLIER,
        refund,
        qty,
        "Evidence supports the claim; the supplier is asked to confirm.",
    )


class ClaimsAgent(Agent):
    kind = "claims"
    prompt_name = "claims_agent"
    tools = frozenset({"assess_claim", "refund", "escalate"})

    def __init__(self, *, llm: LLM, bus: MessageBus, clock: Clock) -> None:
        super().__init__(
            code="swarm",
            display_name="Swarm claims",
            owner="Swarm",
            mandate={
                "auto_refund_limit_cents": AUTO_REFUND_LIMIT_CENTS,
                "min_confidence": MIN_CONFIDENCE,
            },
            llm=llm,
            bus=bus,
            clock=clock,
        )

    def check(self, action: Action) -> Verdict:
        if action.tool == "refund":
            amount = int(action.args.get("amount_cents", 0))
            if amount > AUTO_REFUND_LIMIT_CENTS and not action.args.get("approved_by_person"):
                return Verdict.deny("OVER_AUTO_LIMIT", "Refunds above S$50 need a person")
            if amount <= 0:
                return Verdict.deny("INVALID_AMOUNT", "Refund must be positive")
        return Verdict.allow()

    async def assess(
        self, claim: Claim, line: GroupOrderLine, photo: bytes | None, media_type: str | None
    ) -> tuple[ClaimAssessment, str]:
        readable = photo if media_type in IMAGE_TYPES else None
        unclear = ClaimAssessment(
            issue_type="UNCLEAR",
            claim_supported=False,
            confidence=0.0,
            qty_affected=0,
            evidence="Nothing has looked at the photo yet." if photo else "No photo was sent.",
        )
        if readable is None:
            return unclear, "fallback"
        delivered = line.qty_delivered if line.qty_delivered is not None else line.qty_requested
        description = (
            f"Order line: {line.qty_requested} x {line.item.name} ({line.item.brand}), "
            f"{delivered} delivered. Claim type: {claim.type.value}. "
            f"Units the owner says are affected: {claim.qty_affected}.\n"
            + wrap_untrusted(
                [(f"owner:{claim.shop_id}", "CLAIM", claim.description or "")], tag="owner_message"
            )
        )
        content: Content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(readable).decode(),
                },
            },
            {"type": "text", "text": description},
        ]
        return await self.ask(
            task="assess",
            content=content,
            schema=ClaimAssessment,
            fallback=lambda: unclear,
            effort="medium",
        )

    async def process(
        self,
        session: AsyncSession,
        engine: MoneyEngine,
        claim_id: uuid.UUID,
        photo: bytes | None = None,
        media_type: str | None = None,
    ) -> Claim:
        claim = await session.get(Claim, claim_id)
        if claim is None:
            raise LookupError("Claim not found")
        if claim.decision != ClaimDecision.PENDING:
            return claim
        line = await session.get(GroupOrderLine, claim.group_order_line_id)
        shop_order = await session.get(ShopOrder, claim.shop_order_id)
        shop = await session.get(Shop, claim.shop_id)
        if line is None or shop_order is None or shop is None:
            raise LookupError("Claim is not linked to an order line")
        await session.refresh(line, ["item"])
        await self.require(session, Action("assess_claim", {"claim": str(claim.id)}))
        assessment, source = await self.assess(claim, line, photo, media_type)
        outcome = decide(claim, line, assessment, reviewed=source != "fallback")
        claim.ai_assessment = {
            **assessment.model_dump(),
            "source": source,
            "decision_reason": outcome.reason,
        }
        claim.amount_cents = outcome.refund_cents
        conversation = f"claim:{claim.id}"

        if outcome.decision == ClaimDecision.AUTO_REFUNDED:
            await self.require(session, Action("refund", {"amount_cents": outcome.refund_cents}))
            payment = await engine.refund_shop_order(
                shop_order.id,
                amount_cents=outcome.refund_cents,
                reason=f"{claim.type.value.title()} {line.item.name}",
                refund_key=f"claim:{claim.id}",
            )
            claim.refund_payment_id = payment.id
        else:
            await self.require(session, Action("escalate", {"to": outcome.decision.value}))
        claim.decision = outcome.decision
        await session.commit()
        await self.say(
            session,
            conversation_id=conversation,
            to=f"owner:{shop.code}",
            type="CLAIM_DECISION",
            text=outcome.reason
            + (
                f" {Money(outcome.refund_cents)} is on its way back to your PayPal."
                if outcome.decision == ClaimDecision.AUTO_REFUNDED
                else ""
            ),
            payload={
                "decision": outcome.decision.value,
                "refund_cents": outcome.refund_cents,
                "confidence": assessment.confidence,
                "assessed_by": source,
            },
        )
        return claim


__all__ = ["ClaimAssessment", "ClaimType", "ClaimsAgent", "decide"]
