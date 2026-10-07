"use client";

/** A supplier's side: its catalog and volume tiers, how it negotiated, its invoices and payouts. */

import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  FileText,
  Gauge,
  Truck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { shortId } from "@/components/feeds";
import { PaymentsGrid, QuotesGrid } from "@/components/grids";
import { StatTile } from "@/components/stats";
import { Card, CardHeader, cx, Empty, ModeBadge, Mono, StatusPill } from "@/components/ui";
import {
  ApiError,
  type InvoiceRow,
  type PaymentRow,
  type QuoteRow,
  type SupplierDetail,
  type SupplierSummary,
} from "@/lib/api";
import { CATEGORY_LABEL, dayTime, money, slotColor, titleCase } from "@/lib/format";

export function SupplierView({ code }: { code: string }) {
  const { data: supplier, error } = useSWR<SupplierDetail>(`/api/suppliers/${code}`);
  const { data: summaries } = useSWR<SupplierSummary[]>("/api/suppliers");
  const { data: quotes } = useSWR<QuoteRow[]>(`/api/suppliers/${code}/quotes`);
  const { data: invoices } = useSWR<InvoiceRow[]>(`/api/suppliers/${code}/invoices`);
  const { data: payouts } = useSWR<PaymentRow[]>(`/api/suppliers/${code}/payouts`);
  const summary = summaries?.find((s) => s.code === code);

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <Empty>
          There&apos;s no supplier called &ldquo;{code}&rdquo;.{" "}
          <Link href="/suppliers" className="underline">
            See all suppliers
          </Link>
          .
        </Empty>
      </div>
    );
  }

  const categories = [...new Set((supplier?.catalog ?? []).map((c) => c.category))];

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <Link
        href="/suppliers"
        className="text-ink-2 hover:text-ink inline-flex items-center gap-1 text-xs"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> All suppliers
      </Link>
      <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="h-3 w-3 rounded-full"
              style={{ background: slotColor(code) }}
              aria-hidden
            />
            <h1 className="text-ink text-2xl font-semibold tracking-tight">
              {supplier?.name ?? "..."}
            </h1>
            {supplier ? <ModeBadge mode={supplier.mode} /> : null}
          </div>
          {supplier ? <p className="text-ink-2 mt-1 text-sm">{supplier.tagline}</p> : null}
        </div>
      </header>

      <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          label="Reliability"
          value={supplier ? `${supplier.reliability}/100` : "-"}
          detail={
            supplier && supplier.reliability < 85
              ? "below the 85 needed to win"
              : "on-time, as-ordered deliveries"
          }
          accent={<Gauge className="text-muted h-3.5 w-3.5" aria-hidden />}
        />
        <StatTile
          label="Delivery"
          value={money(supplier?.delivery_fee_cents ?? 0)}
          detail={supplier ? supplier.delivery_days.map(titleCase).join(", ") : undefined}
          accent={<Truck className="text-muted h-3.5 w-3.5" aria-hidden />}
        />
        <StatTile
          label="Group orders won"
          value={summary?.awards ?? 0}
          accent={<CalendarDays className="text-muted h-3.5 w-3.5" aria-hidden />}
        />
        <StatTile
          label="Paid out by PayPal"
          value={money(summary?.paid_out_cents ?? 0)}
          detail={
            supplier
              ? `after the ${(supplier.platform_fee_bps / 100).toFixed(1)}% Swarm fee`
              : undefined
          }
        />
      </div>

      {/* Catalog */}
      <Card className="mt-6">
        <CardHeader
          title="Catalog and volume tiers"
          subtitle="Public list prices. The supplier agent's floor prices stay private, even from this page."
        />
        <div className="space-y-5 px-5 pb-5">
          {categories.map((category) => (
            <div key={category}>
              <h3 className="text-muted mb-2 text-xs font-medium">
                {CATEGORY_LABEL[category] ?? category}
              </h3>
              <ul className="divide-line border-line divide-y rounded-xl border">
                {supplier?.catalog
                  .filter((c) => c.category === category)
                  .map((item) => (
                    <li
                      key={item.sku}
                      className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center"
                    >
                      <div className="min-w-0 sm:w-64">
                        <div className="text-ink truncate text-sm font-medium">{item.name}</div>
                        <div className="text-muted text-xs">
                          {item.brand} · per {item.unit}
                        </div>
                      </div>
                      <ol className="flex flex-wrap gap-1.5">
                        {item.tiers.map((tier, index) => (
                          <li
                            key={tier.min_qty}
                            className={cx(
                              "tabular rounded-lg border px-2 py-1 text-xs",
                              index === item.tiers.length - 1
                                ? "bg-surface-2 text-ink border-transparent"
                                : "border-line text-ink-2",
                            )}
                          >
                            <span className="text-muted">
                              {tier.min_qty === 1 ? "any" : `${tier.min_qty}+`}
                            </span>{" "}
                            <span className="font-medium">{money(tier.unit_price_cents)}</span>
                          </li>
                        ))}
                      </ol>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
          {supplier && supplier.catalog.length === 0 ? <Empty>No items listed.</Empty> : null}
        </div>
      </Card>

      {/* Invoices */}
      <Card className="mt-6">
        <CardHeader
          title="Invoices"
          subtitle="Sent through PayPal Invoicing; Swarm's coordinator checks every line against the agreed prices before paying."
          icon={FileText}
        />
        <div className="px-5 pb-5">
          {invoices && invoices.length ? (
            <ul className="space-y-3">
              {invoices.map((invoice) => (
                <InvoiceCard key={invoice.id} invoice={invoice} />
              ))}
            </ul>
          ) : (
            <Empty>No invoices yet. Suppliers invoice on Friday, after delivery.</Empty>
          )}
        </div>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Quotes"
            subtitle="Every round of every negotiation, landed price including delivery"
          />
          <div className="px-4 pb-4">
            <QuotesGrid rows={quotes} height={340} />
          </div>
        </Card>
        <Card>
          <CardHeader title="Payouts" subtitle="PayPal Payouts to this supplier" />
          <div className="px-4 pb-4">
            <PaymentsGrid
              rows={payouts?.filter((p) => p.kind === "PAYOUT")}
              showParties={false}
              height={340}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}

export function InvoiceCard({ invoice }: { invoice: InvoiceRow }) {
  const report = invoice.report ?? {};
  const approved = invoice.check_status === "APPROVED";
  const rejected = invoice.check_status === "REJECTED";
  return (
    <li className={cx("rounded-xl border p-3", rejected ? "border-critical/40" : "border-line")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-ink font-mono text-sm font-medium">{invoice.number}</span>
        <ModeBadge mode={invoice.mode} compact />
        {approved ? (
          <StatusPill tone="good">Checked</StatusPill>
        ) : rejected ? (
          <StatusPill tone="critical">Rejected</StatusPill>
        ) : (
          <StatusPill tone="neutral">Waiting for check</StatusPill>
        )}
        {invoice.paypal_status ? (
          <span className="text-muted text-xs">
            PayPal: {invoice.paypal_status.replaceAll("_", " ").toLowerCase()}
          </span>
        ) : null}
        <span className="tabular text-ink ml-auto text-sm font-semibold">
          {money(invoice.total_cents)}
        </span>
      </div>
      {approved && report.summary ? (
        <p className="text-ink-2 mt-2 flex items-start gap-1.5 text-sm">
          <CheckCircle2 className="text-good-ink mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {report.summary}
        </p>
      ) : null}
      {rejected && report.issues?.length ? (
        <ul className="text-critical mt-2 space-y-1 text-sm">
          {report.issues.map((issue, index) => (
            <li key={index} className="flex items-start gap-1.5">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {issue.text}
            </li>
          ))}
          {report.overcharge_cents ? (
            <li className="text-ink-2 pl-5.5 text-xs">
              Billed {money(report.invoiced_total_cents ?? 0)} for{" "}
              {money(report.expected_total_cents ?? 0)} of goods: Swarm didn&apos;t pay it and asked
              for a corrected invoice.
            </li>
          ) : null}
        </ul>
      ) : null}
      <div className="text-muted mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span>{dayTime(invoice.at)}</span>
        {invoice.paypal_invoice_id ? (
          <span>
            PayPal invoice <Mono>{shortId(invoice.paypal_invoice_id)}</Mono>
          </span>
        ) : null}
        {invoice.issued_via ? (
          <span>issued via {invoice.issued_via.replaceAll("_", " ")}</span>
        ) : null}
        <Link
          href={`/orders/${invoice.group_order_id}`}
          className="text-ink-2 hover:text-ink ml-auto font-medium"
        >
          Group order →
        </Link>
      </div>
    </li>
  );
}
