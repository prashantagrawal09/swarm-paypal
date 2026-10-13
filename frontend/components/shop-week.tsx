"use client";

/**
 * One shop's week, step by step: what its agent did each day, and what happened to the
 * money (held, then charged for what arrived, the rest released).
 */

import {
  CalendarCheck,
  Handshake,
  type LucideIcon,
  PackageCheck,
  Repeat2,
  Route,
  Sunrise,
  Undo2,
  Wallet,
  Zap,
} from "lucide-react";

import { HoldBar } from "@/components/charts/hold-bar";
import { Card, CardHeader, cx } from "@/components/ui";
import type { PaymentRow, ShopDetail, ShopOrderLine, Step, SwapRow } from "@/lib/api";
import { dayTime, money } from "@/lib/format";
import { shopWeek, type WeekEventKind } from "@/lib/shop-week";

const LOOK: Record<WeekEventKind, { icon: LucideIcon; chip: string }> = {
  proposal: { icon: Sunrise, chip: "bg-surface-2 text-ink-2" },
  deal: { icon: Handshake, chip: "bg-surface-2 text-ink-2" },
  hold: { icon: Wallet, chip: "bg-honey-soft text-honey-ink" },
  flash: { icon: Zap, chip: "bg-honey-soft text-honey-ink" },
  delivery: { icon: PackageCheck, chip: "bg-good-soft text-good-ink" },
  refund: { icon: Undo2, chip: "bg-warning-soft text-warning-ink" },
  swap: { icon: Repeat2, chip: "bg-surface-2 text-ink-2" },
  report: { icon: CalendarCheck, chip: "bg-good-soft text-good-ink" },
};

export function ShopWeekCard({
  shop,
  orders,
  payments,
  swaps,
  steps,
  productName,
}: {
  shop: ShopDetail;
  orders: ShopOrderLine[];
  payments: PaymentRow[];
  swaps: SwapRow[];
  steps: Step[];
  /** Product code -> everyday name ("milk"). */
  productName: (product: string) => string;
}) {
  const { events, money: totals } = shopWeek({
    shop,
    orders,
    payments,
    swaps,
    steps,
    productName: (line) => productName(line.product),
  });
  const settled = totals.chargedCents > 0;

  return (
    <Card>
      <CardHeader
        title={`${shop.name}'s week, step by step`}
        subtitle="What the agent did, and what happened to the money"
        icon={Route}
      />
      {events.length === 0 ? (
        <p className="text-ink-2 px-5 pb-5 text-sm">
          Nothing yet this week. The agent&apos;s proposal goes out on Monday morning.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-x-8 gap-y-6 px-5 pb-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <ol className="relative">
            {events.map((event, index) => {
              const { icon: Icon, chip } = LOOK[event.kind];
              const last = index === events.length - 1;
              return (
                <li key={event.key} className="relative flex gap-3 pb-4 last:pb-0">
                  {last ? null : (
                    <span
                      className="bg-line absolute top-8 bottom-0 left-[15px] w-px"
                      aria-hidden
                    />
                  )}
                  <span
                    className={cx(
                      "relative grid h-8 w-8 shrink-0 place-items-center rounded-full",
                      chip,
                    )}
                    aria-hidden
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 pt-0.5">
                    {event.at ? (
                      <div className="text-muted tabular text-[11px]">{dayTime(event.at)}</div>
                    ) : null}
                    <p className="text-ink text-sm leading-snug font-medium">{event.title}</p>
                    {event.detail ? (
                      <p className="text-ink-2 mt-0.5 text-xs leading-snug">{event.detail}</p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>

          <aside
            className="border-line bg-surface-2/50 self-start rounded-xl border p-4"
            aria-label="This week's money"
          >
            <h3 className="text-ink text-xs font-semibold">The money on this week&apos;s orders</h3>
            {totals.heldCents === 0 ? (
              <p className="text-ink-2 mt-2 text-xs">
                Nothing has been held yet. PayPal holds each shop&apos;s share on Wednesday, once
                the deals are agreed.
              </p>
            ) : (
              <>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <Figure label="Held" swatch="var(--honey)" cents={totals.heldCents} />
                  <Figure
                    label="Charged"
                    swatch="var(--good)"
                    cents={totals.chargedCents}
                    pending={!settled}
                  />
                  <Figure
                    label="Released"
                    swatch="var(--warning)"
                    cents={totals.releasedCents}
                    pending={!settled}
                  />
                </dl>
                {settled ? (
                  <HoldBar
                    className="mt-3 h-7"
                    holdCents={totals.heldCents}
                    chargedCents={totals.chargedCents}
                    label={`Of the ${money(totals.heldCents)} held, ${money(totals.chargedCents)} was charged and ${money(totals.releasedCents)} released.`}
                  />
                ) : (
                  <div
                    className="bg-honey-soft border-honey mt-3 h-7 rounded-lg border border-dashed"
                    role="img"
                    aria-label={`${money(totals.heldCents)} is held and has not been charged yet.`}
                  />
                )}
                <p className="text-ink-2 mt-2.5 text-xs leading-snug">
                  {settled
                    ? totals.releasedCents > 0
                      ? "Charged for what arrived. The hatched part was never taken."
                      : "Everything arrived, so the whole hold became the charge."
                    : "Held, not taken. It becomes a charge only for what is delivered."}
                  {totals.refundedCents > 0
                    ? ` ${money(totals.refundedCents)} was refunded afterwards for a claim.`
                    : ""}
                </p>
              </>
            )}
          </aside>
        </div>
      )}
    </Card>
  );
}

function Figure({
  label,
  swatch,
  cents,
  pending = false,
}: {
  label: string;
  /** A status colour for the mark; the number stays in ink. */
  swatch: string;
  cents: number;
  pending?: boolean;
}) {
  return (
    <div>
      <dt className="text-muted flex items-center gap-1">
        <span className="h-2 w-2 rounded-full" style={{ background: swatch }} aria-hidden />
        {label}
      </dt>
      <dd className="tabular text-ink mt-0.5 text-sm font-semibold">
        {pending ? <span className="text-muted font-normal">not yet</span> : money(cents)}
      </dd>
    </div>
  );
}
