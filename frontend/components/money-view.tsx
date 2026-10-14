"use client";

/** Where every cent went: PayPal activity, the double-entry ledger, invoices and flash deals. */

import { BookCheck, BookX, Scale, Waypoints, Zap } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";

import { MoneyFlowChart } from "@/components/charts/money-flow";
import { useNames } from "@/components/feeds";
import { PaymentsGrid } from "@/components/grids";
import { PayPalUsageCard } from "@/components/paypal-usage";
import { StatTile } from "@/components/stats";
import { InvoiceCard } from "@/components/supplier-view";
import { Card, CardHeader, cx, LoadingRows, Empty, Status } from "@/components/ui";
import type { FlashDeal, InvoiceRow, Ledger, Mode, MoneyFlow, PaymentRow } from "@/lib/api";
import { dayTime, money } from "@/lib/format";

const ACCOUNT_LABEL: Record<string, string> = {
  "platform:clearing": "Swarm's PayPal balance (pass-through)",
  "platform:fees": "Swarm fee income",
  "platform:holds": "Holds outstanding (memo)",
};

const SUB_LABEL: Record<string, string> = {
  paypal: "PayPal wallet",
  purchases: "goods received",
  on_hold: "held (memo)",
  receivable: "owed by Swarm",
  sales: "sales",
  payable: "owed by Swarm",
};

function accountName(account: string, names: Record<string, string>): string {
  if (ACCOUNT_LABEL[account]) return ACCOUNT_LABEL[account];
  const [kind, code, sub] = account.split(":");
  const who = names[code] ?? code ?? kind;
  return sub ? `${who} · ${SUB_LABEL[sub] ?? sub.replaceAll("_", " ")}` : who;
}

export function MoneyView() {
  const [mode, setMode] = useState<"" | Mode>("");
  const { data: payments } = useSWR<PaymentRow[]>(
    `/api/payments?limit=300${mode ? `&mode=${mode}` : ""}`,
  );
  const { data: ledger } = useSWR<Ledger>("/api/ledger");
  const { data: flow } = useSWR<MoneyFlow>("/api/money-flow");
  const { data: invoices } = useSWR<InvoiceRow[]>("/api/invoices?limit=12");
  const { data: deals } = useSWR<FlashDeal[]>("/api/flash-deals");
  const names = useNames();
  const balanced = ledger
    ? ledger.invariant_gap_cents === 0 && ledger.unbalanced_transactions === 0
    : null;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <h1 className="text-ink text-2xl font-semibold tracking-tight">Money</h1>
      <p className="text-ink-2 mt-1 max-w-2xl text-sm">
        Every PayPal call Swarm made, and the double-entry ledger that has to agree with it. Amounts
        are always computed by code; the agents only ever suggest.
      </p>

      <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          label="Ledger"
          loading={!ledger}
          value={
            balanced === null ? (
              "-"
            ) : balanced ? (
              <span className="inline-flex items-center gap-1.5">
                <BookCheck className="text-good-ink h-4 w-4" aria-hidden /> Balanced
              </span>
            ) : (
              <span className="text-critical-ink inline-flex items-center gap-1.5">
                <BookX className="h-4 w-4" aria-hidden /> Out by{" "}
                {money(ledger?.invariant_gap_cents ?? 0)}
              </span>
            )
          }
          detail="debits equal credits, and the PayPal balance matches"
          accent={<Scale className="text-muted h-3.5 w-3.5" aria-hidden />}
        />
        <StatTile
          label="Ledger entries"
          loading={!ledger}
          value={(ledger?.entries ?? 0).toLocaleString("en-SG")}
        />
        <StatTile
          label="Payments recorded"
          loading={!payments}
          value={(payments?.length ?? 0).toLocaleString("en-SG")}
          detail={mode ? `${mode.toLowerCase()} only` : "latest 300"}
        />
        <StatTile
          label="Failed calls"
          loading={!payments}
          value={(payments?.filter((p) => p.status === "FAILED").length ?? 0).toString()}
          detail="retried safely with the same request ID"
        />
      </div>

      <Card id="flow" className="mt-6 scroll-mt-24">
        <CardHeader
          title="Where the money went this week"
          subtitle="Shops are charged only for what arrived. It passes through Swarm's PayPal balance to suppliers, neighbours and refunds; Swarm keeps its fee."
          icon={Waypoints}
        />
        <div className="px-5 pb-4">
          {flow ? <MoneyFlowChart flow={flow} /> : <div className="h-[440px]" />}
        </div>
      </Card>

      <div className="mt-6">
        <PayPalUsageCard />
      </div>

      <Card className="mt-6">
        <CardHeader
          title="PayPal activity"
          subtitle="Holds, charges, releases, refunds and payouts"
          action={
            <div
              className="bg-surface-2 inline-flex rounded-lg p-0.5 text-xs"
              role="tablist"
              aria-label="PayPal mode"
            >
              {(
                [
                  ["", "All"],
                  ["REAL", "Real sandbox"],
                  ["SIMULATED", "Simulated"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={mode === value}
                  onClick={() => setMode(value)}
                  className={cx(
                    "rounded-md px-2.5 py-1 font-medium whitespace-nowrap",
                    mode === value ? "bg-surface text-ink shadow-sm" : "text-ink-2",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        />
        <div className="px-4 pb-4">
          <PaymentsGrid rows={payments} height={480} />
        </div>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card id="ledger" className="scroll-mt-24">
          <CardHeader
            title="Ledger balances"
            subtitle="Signed balances: debits positive, credits negative"
          />
          <div className="grid grid-cols-1 gap-5 px-5 pb-5 sm:grid-cols-2">
            {ledger
              ? (["platform", "suppliers", "shops"] as const).map((group) => {
                  const entries = Object.entries(ledger.balances[group]).filter(([, v]) => v !== 0);
                  return (
                    <div key={group} className={group === "shops" ? "sm:col-span-2" : undefined}>
                      <h3 className="text-muted mb-1.5 text-xs font-medium capitalize">{group}</h3>
                      {entries.length ? (
                        <ul
                          className={cx(
                            "divide-line divide-y text-sm",
                            group === "shops" && "sm:columns-2 sm:gap-6 sm:divide-y-0",
                          )}
                        >
                          {entries.map(([account, value]) => (
                            <li
                              key={account}
                              className="flex break-inside-avoid justify-between gap-3 py-1.5"
                            >
                              <span className="text-ink-2 truncate">
                                {accountName(account, names)}
                              </span>
                              <span className="tabular text-ink">{money(value)}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-muted text-sm">Nothing yet.</p>
                      )}
                    </div>
                  );
                })
              : null}
          </div>
        </Card>
        <Card>
          <CardHeader
            title="Recent invoices"
            subtitle="PayPal Invoicing, checked by the coordinator"
          />
          <div className="feed max-h-[560px] overflow-y-auto px-5 pb-5">
            {!invoices ? (
              <LoadingRows />
            ) : invoices.length ? (
              <ul className="space-y-3">
                {invoices.map((invoice) => (
                  <InvoiceCard key={invoice.id} invoice={invoice} />
                ))}
              </ul>
            ) : (
              <Empty>No invoices yet.</Empty>
            )}
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader
          title="Flash deals"
          subtitle="Suppliers clearing stock; shop agents buy within their owner's rules"
          icon={Zap}
        />
        <div className="px-5 pb-5">
          {!deals ? (
            <LoadingRows rows={1} />
          ) : deals.length ? (
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {deals.map((deal) => (
                <li key={deal.id} className="border-line rounded-xl border p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-ink font-medium">{deal.item}</span>
                    <span className="text-ink-2">· {deal.supplier.name}</span>
                    <span className="ml-auto">
                      <Status value={deal.status} />
                    </span>
                  </div>
                  <div className="tabular text-ink-2 mt-1">
                    <span className="text-ink font-semibold">{money(deal.price_cents)}</span>{" "}
                    <span className="text-muted line-through">{money(deal.list_price_cents)}</span>{" "}
                    per {deal.unit}
                    {deal.discount_pct ? (
                      <span className="text-good-ink ml-1">−{deal.discount_pct}%</span>
                    ) : null}
                    <span className="ml-2">
                      {deal.taken}/{deal.qty} taken
                    </span>
                  </div>
                  {deal.expires_at ? (
                    <div className="text-muted mt-1 text-xs">Ends {dayTime(deal.expires_at)}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No flash deals yet. One comes up on Wednesday.</Empty>
          )}
        </div>
      </Card>
    </div>
  );
}
