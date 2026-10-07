"use client";

/** The shop and supplier directories. */

import { ChevronRight, Gauge, Truck } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { Card, Empty, Meter, ModeBadge, Status, StatusPill } from "@/components/ui";
import type { ShopSummary, SupplierSummary } from "@/lib/api";
import { CATEGORY_EMOJI, initials, money, moneyWhole, slotColor, titleCase } from "@/lib/format";
import { useLive } from "@/lib/live";
import { useNow } from "@/lib/use-now";

export function ShopDirectory() {
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const { activity } = useLive();
  const now = useNow(1000);
  const total = (shops ?? []).reduce((sum, s) => sum + s.saved_week_cents, 0);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-ink text-2xl font-semibold tracking-tight">Shops</h1>
          <p className="text-ink-2 mt-1 text-sm">
            {shops
              ? `${shops.length} independent food shops in Tiong Bahru, each with its own agent.`
              : "Loading..."}
          </p>
        </div>
        {shops ? (
          <p className="text-ink-2 text-sm">
            <span className="tabular text-ink text-lg font-semibold">{money(total)}</span> saved
            between them this week
          </p>
        ) : null}
      </div>
      {shops && shops.length === 0 ? <Empty>No shops yet. Run make seed.</Empty> : null}
      <ul className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(shops ?? []).map((shop) => {
          const recent = activity[shop.code];
          return (
            <li key={shop.code}>
              <Link href={`/shop/${shop.code}`} className="group block h-full">
                <Card className="group-hover:border-line-strong flex h-full flex-col p-4 transition">
                  <div className="flex items-start gap-3">
                    <span className="bg-surface-2 text-ink relative grid h-10 w-10 shrink-0 place-items-center rounded-full text-xs font-semibold">
                      {initials(shop.name).toUpperCase()}
                      {recent && now - recent.at < 3000 ? (
                        <span
                          className="ping border-honey absolute inset-0 rounded-full border-2"
                          aria-hidden
                          key={recent.at}
                        />
                      ) : null}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h2 className="text-ink truncate text-sm font-semibold">{shop.name}</h2>
                        <ModeBadge mode={shop.mode} compact />
                      </div>
                      <p className="text-ink-2 truncate text-xs">
                        {shop.owner} · {shop.kind}
                      </p>
                    </div>
                    <ChevronRight
                      className="text-muted h-4 w-4 transition group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </div>
                  <div className="mt-4 flex items-baseline justify-between">
                    <span className="text-ink-2 text-xs">Saved this week</span>
                    <span className="tabular text-ink text-base font-semibold">
                      {money(shop.saved_week_cents)}
                    </span>
                  </div>
                  <div className="mt-3">
                    <div className="text-muted mb-1 flex justify-between text-[11px]">
                      <span>Spending</span>
                      <span className="tabular">
                        {money(shop.committed_cents)} / {moneyWhole(shop.limit_cents)}
                      </span>
                    </div>
                    <Meter
                      value={shop.committed_cents}
                      max={shop.limit_cents}
                      label={`${shop.name} weekly limit used`}
                    />
                  </div>
                  <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-4">
                    {!shop.connected ? (
                      <StatusPill tone="warning">PayPal not connected</StatusPill>
                    ) : null}
                    {shop.pending_approvals ? (
                      <StatusPill tone="warning">{shop.pending_approvals} to approve</StatusPill>
                    ) : null}
                    {shop.orders.length && new Set(shop.orders.map((o) => o.status)).size === 1 ? (
                      // Every order at the same stage: one pill, with the categories beside it.
                      <span className="inline-flex items-center gap-1.5 text-xs">
                        <Status value={shop.orders[0].status} />
                        <span
                          className="text-ink-2"
                          title={shop.orders.map((o) => o.category).join(", ")}
                        >
                          {shop.orders.length} order{shop.orders.length > 1 ? "s" : ""}{" "}
                          <span aria-hidden>
                            {shop.orders.map((o) => CATEGORY_EMOJI[o.category]).join("")}
                          </span>
                        </span>
                      </span>
                    ) : (
                      shop.orders.map((order) => (
                        <span
                          key={order.category}
                          className="inline-flex items-center gap-1 text-xs"
                        >
                          <span aria-hidden>{CATEGORY_EMOJI[order.category]}</span>
                          <Status value={order.status} />
                        </span>
                      ))
                    )}
                    {shop.connected && shop.orders.length === 0 && !shop.pending_approvals ? (
                      <span className="text-muted text-xs">No orders this week yet</span>
                    ) : null}
                  </div>
                </Card>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function SupplierDirectory() {
  const { data: suppliers } = useSWR<SupplierSummary[]>("/api/suppliers");
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <h1 className="text-ink text-2xl font-semibold tracking-tight">Suppliers</h1>
      <p className="text-ink-2 mt-1 text-sm">
        Each supplier has its own agent that quotes, counters and invoices. Only suppliers with
        reliability of 85 or more can win an order.
      </p>
      <ul className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        {(suppliers ?? []).map((supplier) => (
          <li key={supplier.code}>
            <Link href={`/supplier/${supplier.code}`} className="group block h-full">
              <Card className="group-hover:border-line-strong flex h-full flex-col p-5 transition">
                <div className="flex items-center gap-2">
                  <span
                    className="h-3 w-3 rounded-full"
                    style={{ background: slotColor(supplier.code) }}
                    aria-hidden
                  />
                  <h2 className="text-ink text-base font-semibold">{supplier.name}</h2>
                  <ModeBadge mode={supplier.mode} compact />
                </div>
                <p className="text-ink-2 mt-1.5 text-sm">{supplier.tagline}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-muted flex items-center gap-1 text-xs">
                      <Gauge className="h-3.5 w-3.5" aria-hidden /> Reliability
                    </dt>
                    <dd className="tabular text-ink font-medium">{supplier.reliability}/100</dd>
                  </div>
                  <div>
                    <dt className="text-muted flex items-center gap-1 text-xs">
                      <Truck className="h-3.5 w-3.5" aria-hidden /> Delivery
                    </dt>
                    <dd className="tabular text-ink font-medium">
                      {money(supplier.delivery_fee_cents)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted text-xs">Orders won</dt>
                    <dd className="tabular text-ink font-medium">{supplier.awards ?? 0}</dd>
                  </div>
                  <div>
                    <dt className="text-muted text-xs">Paid out</dt>
                    <dd className="tabular text-ink font-medium">
                      {money(supplier.paid_out_cents ?? 0)}
                    </dd>
                  </div>
                </dl>
                <p className="text-muted mt-auto pt-4 text-xs">
                  Delivers {supplier.delivery_days.map(titleCase).join(", ")}. Style:{" "}
                  {supplier.style}.
                </p>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
