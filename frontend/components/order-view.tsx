"use client";

/** One group order end to end: the deal, each shop's hold and charge, the invoice, the talk. */

import type { ColDef, ICellRendererParams } from "ag-grid-community";
import { ArrowLeft, MessagesSquare } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { DataGrid } from "@/components/data-grid";
import { AgentFeed, shortId } from "@/components/feeds";
import { GroupOrderCard } from "@/components/group-order-card";
import { NegotiationChart } from "@/components/charts/negotiation-chart";
import { PriceLadder } from "@/components/charts/price-ladder";
import { InvoiceCard } from "@/components/supplier-view";
import { Card, CardHeader, Empty, ModeBadge, Mono, Status } from "@/components/ui";
import { ApiError, type GroupOrderDetail } from "@/lib/api";
import { CATEGORY_LABEL, money, shortDate } from "@/lib/format";

type ShopRow = GroupOrderDetail["shop_orders"][number] & {
  id: string;
  lines_text: string;
  short_text: string;
};

export function OrderView({ id }: { id: string }) {
  const { data: group, error } = useSWR<GroupOrderDetail>(`/api/group-orders/${id}`);

  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <Empty>That group order doesn&apos;t exist (maybe the demo was reset).</Empty>
      </div>
    );
  }

  const rows: ShopRow[] = (group?.shop_orders ?? []).map((so) => ({
    ...so,
    id: so.shop.code,
    lines_text: so.lines.map((l) => `${l.qty_requested} ${l.item}`).join(", "),
    short_text: so.lines
      .filter((l) => l.qty_delivered !== null && l.qty_delivered < l.qty_requested)
      .map((l) => `${l.qty_delivered}/${l.qty_requested} ${l.item}`)
      .join(", "),
  }));

  const columns: ColDef<ShopRow>[] = [
    {
      headerName: "Shop",
      minWidth: 150,
      valueGetter: (p) => p.data?.shop.name,
      cellRenderer: (p: ICellRendererParams<ShopRow>) =>
        p.data ? (
          <Link href={`/shop/${p.data.shop.code}`} className="text-ink font-medium hover:underline">
            {p.data.shop.name}
          </Link>
        ) : null,
    },
    { field: "lines_text", headerName: "Ordered", minWidth: 200, tooltipField: "lines_text" },
    {
      field: "short_text",
      headerName: "Short",
      minWidth: 120,
      cellClass: "text-critical-ink",
      tooltipField: "short_text",
    },
    {
      field: "hold_cents",
      headerName: "Held",
      type: "rightAligned",
      cellClass: "tabular",
      valueFormatter: (p) => money(p.value),
      minWidth: 100,
    },
    {
      field: "captured_cents",
      headerName: "Charged",
      type: "rightAligned",
      cellClass: "tabular",
      valueFormatter: (p) => money(p.value),
      minWidth: 100,
    },
    {
      field: "refunded_cents",
      headerName: "Refunded",
      type: "rightAligned",
      cellClass: "tabular",
      valueFormatter: (p) => (p.value ? money(p.value) : "-"),
      minWidth: 100,
    },
    {
      field: "delivery_share_cents",
      headerName: "Delivery share",
      type: "rightAligned",
      cellClass: "tabular",
      valueFormatter: (p) => money(p.value),
      minWidth: 120,
    },
    {
      field: "status",
      headerName: "Money",
      minWidth: 120,
      cellRenderer: (p: ICellRendererParams) =>
        p.value ? (
          <div className="flex h-full items-center leading-normal">
            <Status value={p.value} />
          </div>
        ) : null,
    },
    {
      headerName: "PayPal",
      minWidth: 90,
      maxWidth: 100,
      valueGetter: (p) => p.data?.shop.mode,
      cellRenderer: (p: ICellRendererParams) =>
        p.value ? (
          <div className="flex h-full items-center leading-normal">
            <ModeBadge mode={p.value} compact />
          </div>
        ) : null,
    },
    {
      field: "authorization_id",
      headerName: "Authorization",
      minWidth: 150,
      cellRenderer: (p: ICellRendererParams) =>
        p.value ? <Mono>{shortId(String(p.value))}</Mono> : "-",
    },
  ];

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <Link
        href="/live"
        className="text-ink-2 hover:text-ink inline-flex items-center gap-1 text-xs"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Live board
      </Link>
      <h1 className="text-ink mt-3 text-2xl font-semibold tracking-tight">
        {group
          ? `${CATEGORY_LABEL[group.category] ?? group.category}, week of ${shortDate(`${group.week}T00:00:00+08:00`)}`
          : "Group order"}
      </h1>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="space-y-6">
          {group ? (
            <GroupOrderCard group={group} compact heading="h2" />
          ) : (
            <Card className="h-64 animate-pulse" />
          )}
          <Card className="flex h-[560px] flex-col">
            <CardHeader
              title="The conversation"
              subtitle="Everything the agents said about this order"
              icon={MessagesSquare}
            />
            {group ? (
              <AgentFeed
                className="flex-1"
                conversations={[group.conversation_id, `invoice:${group.id}`].filter(
                  (id): id is string => Boolean(id),
                )}
              />
            ) : null}
          </Card>
        </div>
        <div className="min-w-0 space-y-6">
          {group && group.ladder.length ? (
            <Card>
              <CardHeader
                title="Price ladders"
                subtitle="Each product's volume tiers and where this order landed"
              />
              <div className="grid grid-cols-1 gap-6 px-5 pb-5 xl:grid-cols-2">
                {group.ladder.map((entry) => (
                  <div key={entry.product}>
                    <div className="text-ink-2 mb-1 text-xs font-medium first-letter:uppercase">
                      {entry.name}
                    </div>
                    <PriceLadder entry={entry} shops={group.shops} />
                  </div>
                ))}
              </div>
            </Card>
          ) : null}
          {group && group.quotes.length ? (
            <Card>
              <CardHeader
                title="Negotiation"
                subtitle="Landed price per supplier, round by round"
              />
              <div className="px-5 pb-5">
                <NegotiationChart group={group} />
              </div>
            </Card>
          ) : null}
          <Card>
            <CardHeader
              title="Shops in this order"
              subtitle="Each shop's PayPal hold, what was charged on delivery, and any refund"
            />
            <div className="px-4 pb-4">
              <DataGrid
                rows={group ? rows : undefined}
                columns={columns}
                height={Math.min(520, 120 + rows.length * 44)}
              />
            </div>
          </Card>
          <Card>
            <CardHeader title="Invoices" subtitle="Checked line by line before any payout" />
            <div className="px-5 pb-5">
              {group?.invoices.length ? (
                <ul className="space-y-3">
                  {group.invoices.map((invoice) => (
                    <InvoiceCard key={invoice.id} invoice={invoice} />
                  ))}
                </ul>
              ) : (
                <Empty>No invoice yet.</Empty>
              )}
              {group?.payouts.length ? (
                <ul className="text-ink-2 mt-4 space-y-1 text-sm">
                  {group.payouts.map((p) => (
                    <li key={p.sequence} className="tabular flex flex-wrap gap-x-3">
                      <span className="text-ink font-medium">Payout {p.sequence}</span>
                      <span>{money(p.gross_cents)} gross</span>
                      <span>−{money(p.fee_cents)} Swarm fee</span>
                      <span className="text-ink font-medium">
                        {money(p.net_cents)} to the supplier
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
