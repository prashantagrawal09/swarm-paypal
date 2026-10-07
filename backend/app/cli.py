"""Command-line tools.

    python -m app.cli negotiate                     # this Swarm week, every category
    python -m app.cli negotiate --category dairy    # just one group order
    python -m app.cli negotiate --reseed            # fresh demo world first
    python -m app.cli invite cafe-mei               # an owner's Telegram invite + connect link

`negotiate` plays Monday (each shop agent proposes next week's needs; owners approve) and
Tuesday (pooling, then the coordinator negotiates with the three supplier agents), then
prints the conversation and the result. With ANTHROPIC_API_KEY set the agents write their
messages with the model; without it they use their deterministic policies and templates.
"""

from __future__ import annotations

import argparse
import asyncio
import textwrap
from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.coordinator import Coordinator, conversation_id_for
from app.agents.shop_agent import ShopAgent
from app.clock import SwarmClock, at_local, local_time, week_start
from app.db.enums import Category, GroupOrderStatus, ShopStatus
from app.db.models import AgentMessage, GroupOrder, Shop
from app.features import group_buy
from app.features.products import describe_all
from app.llm.client import AnthropicLLM
from app.money.amount import Money
from app.runtime import Runtime, save_clock, start_runtime

Out = Callable[[str], None]
WIDTH = 100


async def run_negotiation(
    session: AsyncSession,
    runtime: Runtime,
    week: date,
    categories: list[Category] | None = None,
    out: Out = print,
) -> list[GroupOrder]:
    clock = runtime.clock
    llm_label = (
        f"model {runtime.llm.model}"
        if isinstance(runtime.llm, AnthropicLLM)
        else "no model configured: deterministic agent policies and templates"
    )
    out(f"Swarm week of {week:%a %d %b %Y}  ({llm_label})")
    out("=" * WIDTH)

    # Monday: forecasts and owner approvals.
    _move(clock, at_local(week, 9))
    shops = list(
        await session.scalars(
            select(Shop).where(Shop.status == ShopStatus.ACTIVE).order_by(Shop.code)
        )
    )
    out(f"\nMONDAY  {len(shops)} shop agents propose next week's order; owners approve\n")
    for index, shop in enumerate(shops):
        agent = ShopAgent(shop, llm=runtime.llm, bus=runtime.bus, clock=clock)
        approval, _ = await agent.weekly_proposal(session, week)
        if index < 3:
            out(_wrap(f"  {shop.name} -> {shop.owner_name}: {approval.question}", indent=4))
        await agent.confirm_needs(session, week)
    if len(shops) > 3:
        out(f"  ... and {len(shops) - 3} more. All owners tapped Approve.")

    # Tuesday: pool and negotiate.
    _move(clock, at_local(week + timedelta(days=1), 10))
    groups = await group_buy.pool_week(session, week, clock.now())
    coordinator = Coordinator(llm=runtime.llm, bus=runtime.bus, clock=clock)
    done = []
    for group in groups:
        if categories and group.category not in categories:
            continue
        group = await group_buy.load_group(session, group.id)
        pooled = group_buy.pooled_quantities(group)
        out(
            f"\nTUESDAY  {group.category.title()}: {len(group.shop_orders)} shops pooled "
            + describe_all(pooled)
        )
        out("-" * WIDTH)
        if group.status in (GroupOrderStatus.COLLECTING, GroupOrderStatus.NEGOTIATING):
            result = await coordinator.negotiate(session, group.id)
            await print_conversation(session, result.conversation_id, out)
            if result.winner:
                out(
                    f"\n  Result: {result.winner.supplier_name} after {result.rounds} round(s). "
                    f"Best opening {Money(result.opening_best_landed_cents or 0)} -> final "
                    f"{Money(result.winner.landed_total_cents)} landed "
                    f"(saved {Money(result.saved_by_negotiation_cents)} by negotiating)."
                )
        else:
            out(f"  Already {group.status.lower()}; replaying the conversation.")
            await print_conversation(session, conversation_id_for(week, group.category), out)
        group = await group_buy.load_group(session, group.id)
        if group.status == GroupOrderStatus.AWARDED:
            savings = group_buy.savings_for_group(group)
            total_saved = sum(s.saved_cents for s in savings)
            out(
                f"  Shops save {Money(total_saved)} versus buying alone: "
                + ", ".join(f"{s.shop_code} {Money(s.saved_cents)}" for s in savings[:4])
                + (" ..." if len(savings) > 4 else "")
            )
        done.append(group)
    if isinstance(clock, SwarmClock):
        await save_clock(session, clock)
    return done


async def print_conversation(session: AsyncSession, conversation_id: str, out: Out) -> None:
    rows = await session.scalars(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(AgentMessage.seq)
    )
    for message in rows:
        when = local_time(message.created_at).strftime("%a %H:%M")
        landed = message.payload.get("landed_total_cents")
        extra = ""
        if landed is not None and message.payload.get("strategy"):
            extra = (
                f"  [landed {Money(landed)}, {message.payload.get('strategy')}, "
                f"decided by {message.payload.get('decided_by')}]"
            )
        header = f"  {when}  {message.from_agent} -> {message.to_agent}  {message.type}"
        out(header)
        out(_wrap(message.text + extra, indent=6))


def _wrap(text: str, indent: int) -> str:
    return textwrap.fill(
        text, width=WIDTH, initial_indent=" " * indent, subsequent_indent=" " * indent
    )


def _move(clock: object, instant: object) -> None:
    if isinstance(clock, SwarmClock) and clock.now() < instant:  # type: ignore[operator]
        clock.set(instant)  # type: ignore[arg-type]


async def _negotiate(args: argparse.Namespace) -> None:
    from app.db.session import get_sessionmaker
    from app.seed.seed import reset_database, seed_world

    async with get_sessionmaker()() as session:
        if args.reseed:
            await reset_database(session)
            await seed_world(session, demo_week_start=args.week)
        runtime = await start_runtime(session)
        week = args.week or week_start(runtime.clock.now())
        categories = None if args.category == "all" else [Category(args.category.upper())]
        await run_negotiation(session, runtime, week, categories)


async def _week(args: argparse.Namespace) -> None:
    from app.db.session import get_sessionmaker
    from app.features.context import Ctx
    from app.features.week import WeekRunner

    async with get_sessionmaker()() as session:
        runtime = await start_runtime(session)
        ctx = Ctx(session, runtime)
        runner = WeekRunner(ctx, week_start(runtime.clock.now()))
        while True:
            step, result = await runner.run_next()
            if step is None:
                break
            print(f"{step.title:<28} {result}")
            if not args.all:
                break


def invite(shop_code: str, bot_username: str | None = None) -> list[str]:
    """The signed Telegram invite and Connect-PayPal link for one shop's owner."""
    from datetime import UTC, datetime

    from app.config import get_settings
    from app.security import connect_link, telegram_invite

    settings = get_settings()
    now = datetime.now(UTC)
    payload = telegram_invite(settings, shop_code, now)
    lines = [f"Telegram: send /start {payload} to the bot"]
    if bot_username:
        lines.append(f"          or open https://t.me/{bot_username.lstrip('@')}?start={payload}")
    lines.append(f"PayPal:   {connect_link(settings, shop_code, now)}")
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    negotiate = commands.add_parser("negotiate", help="run Monday and Tuesday of a Swarm week")
    negotiate.add_argument("--week", type=date.fromisoformat, help="the week's Monday")
    negotiate.add_argument(
        "--category", default="all", choices=["all", *[c.value.lower() for c in Category]]
    )
    negotiate.add_argument("--reseed", action="store_true", help="wipe and reseed first")
    week = commands.add_parser("week", help="run the next step of the Swarm week (or --all)")
    week.add_argument("--all", action="store_true", help="run every remaining step")
    owner = commands.add_parser("invite", help="signed links for a shop's owner")
    owner.add_argument("shop", help="shop code, e.g. cafe-mei")
    owner.add_argument("--bot", help="the bot's @username, to print a t.me deep link")
    args = parser.parse_args(argv)
    if args.command == "negotiate":
        asyncio.run(_negotiate(args))
    elif args.command == "week":
        asyncio.run(_week(args))
    elif args.command == "invite":
        print("\n".join(invite(args.shop, args.bot)))


if __name__ == "__main__":
    main()
