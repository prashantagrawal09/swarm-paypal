"use client";

/** One category's group order: who's in, who won, the price ladder and the negotiation. */

import { ChevronRight, Store, Truck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { NegotiationChart } from "@/components/charts/negotiation-chart";
import { PriceLadder } from "@/components/charts/price-ladder";
import { Card, cx, Status } from "@/components/ui";
import type { GroupOrder } from "@/lib/api";
import { CATEGORY_EMOJI, CATEGORY_LABEL, money, slotColor } from "@/lib/format";

type View = "ladder" | "rounds";

export function GroupOrderCard({
  group,
  compact = false,
  heading: Heading = "h3",
}: {
  group: GroupOrder;
  compact?: boolean;
  /** The heading level that fits where the card sits (h2 straight under a page title). */
  heading?: "h2" | "h3";
}) {
  const [view, setView] = useState<View>("ladder");
  const best = [...group.ladder].sort(
    (a, b) =>
      (b.single_price_cents ?? 0) * b.qty -
      (b.agreed_cents ?? b.tier_price_cents ?? 0) * b.qty -
      ((a.single_price_cents ?? 0) * a.qty - (a.agreed_cents ?? a.tier_price_cents ?? 0) * a.qty),
  )[0];
  const [product, setProduct] = useState<string | null>(null);
  const entry = group.ladder.find((l) => l.product === product) ?? best;
  const savedPct =
    group.alone_cents > 0 ? Math.round((group.saved_cents / group.alone_cents) * 100) : 0;
  const negotiated =
    group.opening_landed_cents && group.final_landed_cents
      ? group.opening_landed_cents - group.final_landed_cents
      : 0;

  return (
    <Card as="article" className="flex flex-col">
      <header className="flex items-start gap-3 px-5 pt-4">
        <span
          className="bg-surface-2 grid h-10 w-10 shrink-0 place-items-center rounded-xl text-lg"
          aria-hidden
        >
          {CATEGORY_EMOJI[group.category] ?? "📦"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Heading className="text-ink text-sm font-semibold">
              {CATEGORY_LABEL[group.category] ?? group.category}
            </Heading>
            <Status value={group.status} />
          </div>
          <p className="text-ink-2 mt-0.5 line-clamp-2 text-xs" title={group.pooled_text}>
            {group.pooled_text || "Collecting orders"}
          </p>
        </div>
      </header>

      <dl className="border-line bg-line mt-3 grid grid-cols-3 gap-px overflow-hidden border-y text-center">
        <div className="bg-surface px-2 py-2">
          <dt className="text-muted text-[11px]">Alone</dt>
          <dd className="tabular text-ink-2 decoration-muted/60 text-sm line-through">
            {money(group.alone_cents)}
          </dd>
        </div>
        <div className="bg-surface px-2 py-2">
          <dt className="text-muted text-[11px]">Together</dt>
          <dd className="tabular text-ink text-sm font-medium">{money(group.paid_cents)}</dd>
        </div>
        <div className="bg-surface px-2 py-2">
          <dt className="text-muted text-[11px]">Saved</dt>
          <dd className="tabular text-good-ink text-sm font-semibold">
            {money(group.saved_cents)}
            {savedPct ? (
              <span className="text-muted ml-1 text-[11px] font-normal">{savedPct}%</span>
            ) : null}
          </dd>
        </div>
      </dl>

      <div className="text-ink-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-5 pt-3 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <Store className="text-muted h-3.5 w-3.5" aria-hidden />
          {group.shops} shops
        </span>
        {group.supplier ? (
          <span className="inline-flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: slotColor(group.supplier.code) }}
              aria-hidden
            />
            {group.supplier.name}
          </span>
        ) : null}
        {group.rounds ? <span>{group.rounds} rounds</span> : null}
        {negotiated > 0 ? (
          <span className="text-good-ink">−{money(negotiated)} negotiated</span>
        ) : null}
        {group.delivery_fee_cents ? (
          <span className="inline-flex items-center gap-1.5">
            <Truck className="text-muted h-3.5 w-3.5" aria-hidden />{" "}
            {money(group.delivery_fee_cents)} shared
          </span>
        ) : null}
      </div>

      {!compact && (entry || group.quotes.length) ? (
        <div className="px-5 pt-3 pb-4">
          <div className="mb-2 flex items-center gap-2">
            <div className="bg-surface-2 inline-flex rounded-lg p-0.5 text-xs" role="tablist">
              {(["ladder", "rounds"] as View[]).map((key) => (
                <button
                  key={key}
                  role="tab"
                  aria-selected={view === key}
                  disabled={key === "rounds" && group.quotes.length === 0}
                  onClick={() => setView(key)}
                  className={cx(
                    "rounded-md px-2.5 py-1 font-medium whitespace-nowrap transition disabled:opacity-40",
                    view === key ? "bg-surface text-ink shadow-sm" : "text-ink-2",
                  )}
                >
                  {key === "ladder" ? "Price ladder" : "Negotiation"}
                </button>
              ))}
            </div>
            {view === "ladder" && group.ladder.length > 1 ? (
              <select
                value={entry?.product}
                onChange={(event) => setProduct(event.target.value)}
                className="border-line bg-surface text-ink-2 ml-auto max-w-[50%] truncate rounded-lg border px-2 py-1 text-xs"
                aria-label="Product"
              >
                {group.ladder.map((l) => (
                  <option key={l.product} value={l.product}>
                    {l.name}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          {view === "ladder" && entry ? (
            <PriceLadder key={entry.product} entry={entry} shops={group.shops} />
          ) : view === "rounds" ? (
            <NegotiationChart group={group} />
          ) : null}
        </div>
      ) : null}

      {group.excluded.length ? (
        <p className="bg-surface-2 text-ink-2 mx-5 mb-3 rounded-lg px-3 py-2 text-xs">
          {group.excluded.length} line{group.excluded.length > 1 ? "s" : ""} kept out by brand
          rules: {group.excluded[0].reason}
          {group.excluded.length > 1 ? ` (and ${group.excluded.length - 1} more)` : ""}.
        </p>
      ) : null}

      {compact ? null : (
        <Link
          href={`/orders/${group.id}`}
          className="border-line text-ink-2 hover:bg-surface-2 hover:text-ink mt-auto flex items-center justify-between border-t px-5 py-2.5 text-xs font-medium transition"
        >
          Shops, holds and invoices
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      )}
    </Card>
  );
}
