"use client";

/**
 * PayPal, capability by capability: what Swarm uses each one for, the REST call behind it,
 * and the completed calls that back it up so far, split into real sandbox calls and
 * simulated ones. A capability with nothing against it yet says so.
 */

import {
  BadgeDollarSign,
  FileCheck2,
  Hand,
  Landmark,
  type LucideIcon,
  RefreshCw,
  ShieldCheck,
  Undo2,
  Vault,
  Webhook,
  XCircle,
} from "lucide-react";
import useSWR from "swr";

import { Card, CardHeader, cx, Mono } from "@/components/ui";
import type { PayPalUsage } from "@/lib/api";
import { money } from "@/lib/format";

const ICON: Record<string, LucideIcon> = {
  vault: Vault,
  authorize: Hand,
  capture: BadgeDollarSign,
  void: XCircle,
  reauthorize: RefreshCw,
  refund: Undo2,
  payouts: Landmark,
  invoicing: FileCheck2,
  webhooks: Webhook,
};

/** What a count of one means for each capability. */
const UNIT: Record<string, [string, string]> = {
  vault: ["wallet saved", "wallets saved"],
  invoicing: ["invoice", "invoices"],
  webhooks: ["event verified", "events verified"],
};

function Count({ value, real }: { value: number; real: boolean }) {
  return (
    <span
      className={cx(
        "tabular inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        value === 0
          ? "bg-surface-2 text-muted"
          : real
            ? "bg-real-soft text-real"
            : "bg-surface-2 text-ink-2",
      )}
      title={real ? "Real PayPal sandbox API calls" : "Simulated PayPal (same rules, no network)"}
    >
      <span
        className={cx("h-1.5 w-1.5 rounded-full", value > 0 && real ? "bg-real" : "bg-muted")}
        aria-hidden
      />
      {value} {real ? "real" : "simulated"}
    </span>
  );
}

export function PayPalUsageCard() {
  const { data } = useSWR<PayPalUsage[]>("/api/paypal-usage");
  const rows = data ?? [];
  const real = rows.reduce((sum, row) => sum + row.real, 0);

  return (
    <Card id="capabilities" className="scroll-mt-24">
      <CardHeader
        title="PayPal, capability by capability"
        subtitle={
          real > 0
            ? "What each one is used for, and the completed calls behind it so far."
            : "What each one is used for, and the completed calls behind it so far. Every call is simulated until sandbox keys are set; the simulator follows the same rules."
        }
        icon={ShieldCheck}
      />
      <ul className="divide-y divide-[var(--line)]">
        {rows.map((row) => {
          const Icon = ICON[row.key] ?? ShieldCheck;
          const used = row.real + row.simulated > 0;
          const [one, many] = UNIT[row.key] ?? ["call", "calls"];
          const total = row.real + row.simulated;
          return (
            <li
              key={row.key}
              className="grid grid-cols-1 gap-x-6 gap-y-2 px-5 py-3.5 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]"
            >
              <div className="flex min-w-0 gap-3">
                <span
                  className={cx(
                    "grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                    used ? "bg-honey-soft text-honey-ink" : "bg-surface-2 text-muted",
                  )}
                  aria-hidden
                >
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <h3 className="text-ink text-sm font-medium">{row.name}</h3>
                  <p className="text-ink-2 text-xs">{row.use}</p>
                  <Mono className="mt-1 block break-all">{row.call}</Mono>
                </div>
              </div>
              <div className="flex flex-col gap-1.5 pl-11 md:items-end md:pl-0 md:text-right">
                <div className="flex flex-wrap items-center gap-1.5 md:justify-end">
                  <Count value={row.real} real />
                  <Count value={row.simulated} real={false} />
                </div>
                <p className="text-ink-2 text-xs">
                  {used ? (
                    <>
                      <span className="tabular text-ink font-medium">{total}</span>{" "}
                      {total === 1 ? one : many}
                      {row.amount_cents > 0 ? (
                        <>
                          , <span className="tabular">{money(row.amount_cents)}</span>
                        </>
                      ) : null}
                    </>
                  ) : (
                    row.when
                  )}
                </p>
                {row.latest ? (
                  <Mono className="block truncate">latest {row.latest.paypal_id}</Mono>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
