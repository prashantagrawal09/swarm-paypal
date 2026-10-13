"use client";

/** One shop's week: what it saved, what it spent against its limit, and every order and payment. */

import {
  ArrowLeft,
  BadgeCheck,
  CircleSlash,
  Leaf,
  MapPin,
  MessageCircle,
  Repeat2,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

import { Dumbbell } from "@/components/charts/dumbbell";
import { ForecastSpark } from "@/components/charts/forecast-spark";
import { ClaimsGrid, OrdersGrid, PaymentsGrid, SwapsGrid } from "@/components/grids";
import { OwnerPhone } from "@/components/owner-phone";
import { ShopWeekCard } from "@/components/shop-week";
import { HeroFigure, StatTile } from "@/components/stats";
import {
  ButtonLink,
  Card,
  CardHeader,
  cx,
  Empty,
  Meter,
  ModeBadge,
  Status,
  StatusPill,
} from "@/components/ui";
import {
  ApiError,
  type ClaimRow,
  type DemoState,
  type PaymentRow,
  type Product,
  type ShopDetail,
  type ShopOrderLine,
  type SwapRow,
} from "@/lib/api";
import { dayTime, kg, money, moneyWhole, time } from "@/lib/format";

type Tab = "orders" | "payments" | "swaps" | "claims";

export function ShopView({ code }: { code: string }) {
  const { data: shop, error } = useSWR<ShopDetail>(`/api/shops/${code}`);
  const { data: orders } = useSWR<ShopOrderLine[]>(`/api/shops/${code}/orders`);
  const { data: payments } = useSWR<PaymentRow[]>(`/api/shops/${code}/payments`);
  const { data: swaps } = useSWR<SwapRow[]>(`/api/shops/${code}/swaps`);
  const { data: claims } = useSWR<ClaimRow[]>(`/api/shops/${code}/claims`);
  const { data: state } = useSWR<DemoState>("/api/demo/state");
  const { data: products } = useSWR<Product[]>("/api/products");
  const [tab, setTab] = useState<Tab>("orders");
  const productName = (product: string) =>
    products?.find((p) => p.product === product)?.name ?? product.replaceAll("-", " ");

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <Empty>
          There&apos;s no shop called &ldquo;{code}&rdquo;.{" "}
          <Link href="/shops" className="underline">
            See all shops
          </Link>
          .
        </Empty>
      </div>
    );
  }

  const report = shop?.report;
  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "orders", label: "Orders", count: orders?.length },
    { key: "payments", label: "PayPal", count: payments?.length },
    { key: "swaps", label: "Neighbours", count: swaps?.length },
    { key: "claims", label: "Claims", count: claims?.length },
  ];

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <Link
        href="/shops"
        className="text-ink-2 hover:text-ink inline-flex items-center gap-1 text-xs"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> All shops
      </Link>

      {/* Header */}
      <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-ink text-2xl font-semibold tracking-tight">
              {shop?.name ?? "..."}
            </h1>
            {shop ? <ModeBadge mode={shop.mode} /> : null}
          </div>
          {shop ? (
            <p className="text-ink-2 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span>
                {shop.owner} · {shop.kind}
              </span>
              <span className="text-muted inline-flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" aria-hidden />
                {shop.address}
              </span>
            </p>
          ) : null}
        </div>
        {shop ? (
          <div className="flex flex-wrap items-center gap-2">
            {shop.connected ? (
              <StatusPill tone="good">PayPal connected</StatusPill>
            ) : (
              <ButtonLink href={`/connect/${shop.code}`} variant="honey">
                Connect PayPal
              </ButtonLink>
            )}
            {shop.telegram_linked ? (
              <StatusPill tone="info">On Telegram</StatusPill>
            ) : (
              <StatusPill tone="neutral">Telegram not linked</StatusPill>
            )}
          </div>
        ) : null}
      </header>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          {/* Savings */}
          <Card className="p-5">
            <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <div>
                <HeroFigure
                  label="Saved this week"
                  value={report?.total_saved_cents ?? 0}
                  format={money}
                  detail={
                    shop ? `${moneyWhole(shop.saved_to_date_cents)} since joining Swarm` : undefined
                  }
                />
                <div className="mt-5">
                  <div className="text-ink-2 flex items-baseline justify-between text-xs">
                    <span>Committed this week</span>
                    <span className="tabular">
                      <span className="text-ink font-medium">
                        {money(shop?.committed_cents ?? 0)}
                      </span>{" "}
                      of {moneyWhole(shop?.limit_cents ?? 0)} limit
                    </span>
                  </div>
                  <div className="mt-1.5">
                    <Meter
                      value={shop?.committed_cents ?? 0}
                      max={shop?.limit_cents ?? 1}
                      label="Weekly spending limit used"
                    />
                  </div>
                  <p className="text-muted mt-1.5 text-[11px]">
                    Above the limit, the agent stops and asks the owner before holding any money.
                  </p>
                </div>
              </div>
              <div>
                <div className="text-ink-2 mb-3 text-xs font-medium">
                  Buying alone vs. buying with Swarm
                </div>
                {report && report.groups.length ? (
                  <Dumbbell
                    rows={report.groups.map((g) => ({
                      category: g.category,
                      alone_cents: g.alone_cents,
                      paid_cents: g.paid_cents,
                      saved_cents: g.saved_cents,
                    }))}
                  />
                ) : (
                  <Empty>Savings show up once this week&apos;s group orders are agreed.</Empty>
                )}
              </div>
            </div>
            <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <StatTile
                label="Group buying"
                value={money(report?.group_saved_cents ?? 0)}
                detail="vs. buying alone"
              />
              <StatTile
                label="Neighbours"
                value={money(
                  (report?.swap_income_cents ?? 0) +
                    (report?.help_income_cents ?? 0) +
                    (report?.swap_saved_cents ?? 0),
                )}
                detail={
                  report
                    ? `${money(report.swap_income_cents + report.help_income_cents)} earned · ${money(report.swap_saved_cents)} saved`
                    : undefined
                }
                accent={<Repeat2 className="text-muted h-3.5 w-3.5" aria-hidden />}
              />
              <StatTile
                label="Flash deals"
                value={money(report?.flash_saved_cents ?? 0)}
                accent={<Zap className="text-muted h-3.5 w-3.5" aria-hidden />}
              />
              <StatTile
                label="Food not wasted"
                value={kg(report?.food_saved_grams ?? 0)}
                detail={
                  report?.refunds_cents ? `${money(report.refunds_cents)} refunded` : undefined
                }
                accent={<Leaf className="text-good-ink h-3.5 w-3.5" aria-hidden />}
              />
            </div>
          </Card>

          {shop && orders && payments && swaps ? (
            <ShopWeekCard
              shop={shop}
              orders={orders}
              payments={payments}
              swaps={swaps}
              steps={state?.steps ?? []}
              productName={productName}
            />
          ) : null}

          {/* Records */}
          <Card>
            <div className="flex items-center gap-1 overflow-x-auto px-4 pt-3" role="tablist">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => setTab(t.key)}
                  className={cx(
                    "shrink-0 rounded-lg px-3 py-1.5 text-sm transition",
                    tab === t.key
                      ? "bg-surface-2 text-ink font-medium"
                      : "text-ink-2 hover:text-ink",
                  )}
                >
                  {t.label}
                  {t.count ? (
                    <span className="tabular text-muted ml-1.5 text-xs">{t.count}</span>
                  ) : null}
                </button>
              ))}
            </div>
            <div className="p-4">
              {tab === "orders" ? <OrdersGrid rows={orders} /> : null}
              {tab === "payments" ? <PaymentsGrid rows={payments} /> : null}
              {tab === "swaps" ? <SwapsGrid rows={swaps} /> : null}
              {tab === "claims" ? <ClaimsGrid rows={claims} /> : null}
            </div>
          </Card>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <Card>
              <CardHeader
                title="Owner decisions"
                subtitle="What the agent asked, and the answers"
              />
              <ul className="divide-line divide-y px-5 pb-3">
                {(shop?.approvals ?? []).map((a) => (
                  <li key={a.id} className="flex items-start gap-3 py-2.5 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="text-ink line-clamp-2">{a.question}</p>
                      <p className="tabular text-muted mt-0.5 text-xs">{dayTime(a.at)}</p>
                    </div>
                    <Status value={a.status} />
                  </li>
                ))}
                {shop && shop.approvals.length === 0 ? (
                  <li className="text-muted py-3 text-sm">No questions yet.</li>
                ) : null}
              </ul>
            </Card>
            <Card>
              <CardHeader
                title="This week's forecast"
                subtitle={shop?.forecast.note || "What the agent expects the shop to need"}
              />
              <div className="space-y-3 px-5 pb-5 text-sm">
                <ul className="divide-line divide-y">
                  {(shop?.forecast.items ?? []).map((item) => (
                    <li
                      key={item.product}
                      className="flex items-center gap-3 py-1.5"
                      title={item.explanation}
                    >
                      <span className="text-ink min-w-0 flex-1 truncate">{item.name}</span>
                      <ForecastSpark
                        history={item.history ?? []}
                        forecast={item.confirmed ?? item.predicted}
                        unit={item.unit}
                      />
                      {item.confirmed !== null && item.confirmed !== item.predicted ? (
                        <span className="tabular text-muted text-xs line-through">
                          {item.predicted}
                        </span>
                      ) : null}
                      <span className="tabular text-ink font-medium">
                        {item.confirmed ?? item.predicted}
                      </span>
                      <span className="text-muted w-20 truncate text-xs">{item.unit}</span>
                    </li>
                  ))}
                </ul>
                {shop?.forecast.items.some((item) => item.history?.length) ? (
                  <p className="text-muted flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="bg-muted h-2.5 w-2 rounded-sm" aria-hidden />
                      the last {shop.forecast.items[0]?.history.length ?? 4} weeks
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="bg-ink h-2.5 w-2 rounded-sm" aria-hidden />
                      this week&apos;s order
                    </span>
                  </p>
                ) : null}
                {shop && Object.keys(shop.accepted_brands).length ? (
                  <ul className="text-ink-2 space-y-1 text-xs">
                    {Object.entries(shop.accepted_brands).map(([product, brands]) => (
                      <li key={product} className="flex items-start gap-1.5">
                        <BadgeCheck
                          className="text-muted mt-0.5 h-3.5 w-3.5 shrink-0"
                          aria-hidden
                        />
                        Only {brands.join(" or ")} for {productName(product).toLowerCase()}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {shop ? (
                  <p className="text-ink-2 flex items-center gap-1.5 text-xs">
                    {shop.allow_substitutes ? (
                      <BadgeCheck className="text-muted h-3.5 w-3.5" aria-hidden />
                    ) : (
                      <CircleSlash className="text-muted h-3.5 w-3.5" aria-hidden />
                    )}
                    {shop.allow_substitutes
                      ? "Happy with equivalent brands otherwise"
                      : "No substitutes"}
                  </p>
                ) : null}
              </div>
            </Card>
          </div>
        </div>

        {/* Owner's phone (demo) */}
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <div className="mb-3 flex items-center gap-2 px-1">
            <MessageCircle className="text-muted h-4 w-4" aria-hidden />
            <h2 className="text-ink text-sm font-semibold">{shop?.owner ?? "Owner"}&apos;s chat</h2>
          </div>
          {state?.demo_mode === false ? (
            <Empty>Owners talk to their agent on Telegram.</Empty>
          ) : (
            <OwnerPhone shop={code} clock={state ? time(state.now) : undefined} />
          )}
        </aside>
      </div>
    </div>
  );
}
