"use client";

/** Column sets for the data grids, shared by the shop, supplier, order and money pages. */

import type { ColDef, ICellRendererParams, ValueFormatterParams } from "ag-grid-community";
import Link from "next/link";

import { DataGrid } from "@/components/data-grid";
import { shortId } from "@/components/feeds";
import { ModeBadge, Mono, Status } from "@/components/ui";
import type { ClaimRow, PaymentRow, QuoteRow, ShopOrderLine, SwapRow } from "@/lib/api";
import { CATEGORY_LABEL, dayTime, humanize, kg, money, shortDate } from "@/lib/format";

const cents = (p: ValueFormatterParams) =>
  p.value === null || p.value === undefined ? "-" : money(Number(p.value));
const right = { type: "rightAligned", cellClass: "tabular" } as const;
const when = (p: ValueFormatterParams) => (p.value ? dayTime(String(p.value)) : "-");

/** Pills sit centred in the row instead of stretching to its height. */
function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full items-center leading-normal">{children}</div>;
}

function StatusCell({ value }: ICellRendererParams) {
  return value ? (
    <Centered>
      <Status value={String(value)} />
    </Centered>
  ) : null;
}

function QuoteStatusCell({ value }: ICellRendererParams) {
  return value ? (
    <Centered>
      <Status value={String(value)} word={value === "AWARDED" ? "Won" : undefined} />
    </Centered>
  ) : null;
}

function ModeCell({ value }: ICellRendererParams) {
  return value ? (
    <Centered>
      <ModeBadge mode={value} compact />
    </Centered>
  ) : null;
}

function IdCell({ value }: ICellRendererParams) {
  return value ? (
    <Mono className="text-ink-2">
      <span title={String(value)}>{shortId(String(value))}</span>
    </Mono>
  ) : (
    <span className="text-muted">-</span>
  );
}

const PAYMENT_KIND: Record<string, string> = {
  AUTHORIZATION: "Hold",
  CAPTURE: "Charge",
  VOID: "Release hold",
  REFUND: "Refund",
  PAYOUT: "Payout",
  REAUTHORIZATION: "Renew hold",
  SWAP_PAYMENT: "Neighbour payment",
};

export function PaymentsGrid({
  rows,
  showParties = true,
  height,
  exportName = "swarm-paypal-activity",
}: {
  rows?: PaymentRow[];
  showParties?: boolean;
  height?: number;
  exportName?: string;
}) {
  const columns: ColDef<PaymentRow>[] = [
    { field: "at", headerName: "When", valueFormatter: when, minWidth: 120, sort: "desc" },
    {
      field: "kind",
      headerName: "What",
      valueFormatter: (p) => PAYMENT_KIND[p.value] ?? humanize(String(p.value)),
      minWidth: 110,
    },
    ...(showParties
      ? ([
          { headerName: "Shop", valueGetter: (p) => p.data?.shop?.name ?? "", minWidth: 130 },
          {
            headerName: "Supplier",
            valueGetter: (p) => p.data?.supplier?.name ?? "",
            minWidth: 130,
          },
        ] as ColDef<PaymentRow>[])
      : []),
    { field: "amount_cents", headerName: "Amount", valueFormatter: cents, ...right, minWidth: 100 },
    { field: "status", headerName: "Status", cellRenderer: StatusCell, minWidth: 120 },
    { field: "mode", headerName: "PayPal", cellRenderer: ModeCell, minWidth: 90, maxWidth: 110 },
    { field: "paypal_id", headerName: "PayPal ID", cellRenderer: IdCell, minWidth: 150 },
  ];
  return (
    <DataGrid
      rows={rows}
      columns={columns}
      height={height}
      empty="No PayPal activity yet."
      exportName={exportName}
    />
  );
}

export function OrdersGrid({ rows, height }: { rows?: ShopOrderLine[]; height?: number }) {
  const columns: ColDef<ShopOrderLine>[] = [
    {
      field: "week",
      headerName: "Week",
      valueFormatter: (p) => shortDate(`${p.value}T00:00:00+08:00`),
      minWidth: 76,
      maxWidth: 90,
    },
    {
      field: "item",
      headerName: "Item",
      minWidth: 160,
      valueGetter: (p) => `${p.data?.item} · ${p.data?.brand}`,
    },
    { field: "supplier", headerName: "Supplier", minWidth: 110 },
    { field: "qty_requested", headerName: "Ordered", ...right, minWidth: 80 },
    {
      field: "qty_delivered",
      headerName: "Arrived",
      ...right,
      minWidth: 80,
      valueFormatter: (p) => (p.value === null || p.value === undefined ? "-" : String(p.value)),
      cellClassRules: {
        "text-critical-ink font-medium": (p) =>
          p.value !== null && p.data !== undefined && p.value < p.data.qty_requested,
      },
    },
    {
      field: "alone_unit_price_cents",
      headerName: "Alone",
      valueFormatter: cents,
      ...right,
      minWidth: 80,
      cellClass: "tabular text-muted line-through",
    },
    {
      field: "unit_price_cents",
      headerName: "Swarm price",
      valueFormatter: cents,
      ...right,
      minWidth: 100,
    },
    {
      field: "line_total_cents",
      headerName: "Line total",
      valueFormatter: cents,
      ...right,
      minWidth: 100,
    },
    { field: "order_status", headerName: "Money", cellRenderer: StatusCell, minWidth: 110 },
  ];
  return (
    <DataGrid
      rows={rows}
      columns={columns}
      height={height}
      empty="No orders yet. The agent proposes the week's order on Monday."
      exportName="swarm-orders"
    />
  );
}

export function SwapsGrid({ rows, height }: { rows?: SwapRow[]; height?: number }) {
  const columns: ColDef<SwapRow>[] = [
    { field: "at", headerName: "When", valueFormatter: when, minWidth: 120, sort: "desc" },
    {
      field: "kind",
      headerName: "Kind",
      valueFormatter: (p) => (p.value === "EMERGENCY" ? "Emergency borrow" : "Surplus sale"),
      minWidth: 130,
    },
    {
      headerName: "Item",
      valueGetter: (p) => `${p.data?.qty} × ${p.data?.product_name}`,
      minWidth: 160,
    },
    { headerName: "From", valueGetter: (p) => p.data?.seller?.name ?? "-", minWidth: 130 },
    {
      headerName: "To",
      valueGetter: (p) => p.data?.buyer?.name ?? "Open to neighbours",
      minWidth: 130,
    },
    { field: "price_cents", headerName: "Price", valueFormatter: cents, ...right, minWidth: 90 },
    {
      field: "food_saved_grams",
      headerName: "Food saved",
      valueFormatter: (p) => (p.value ? kg(Number(p.value)) : "-"),
      ...right,
      minWidth: 100,
    },
    { field: "status", headerName: "Status", cellRenderer: StatusCell, minWidth: 110 },
  ];
  return (
    <DataGrid
      rows={rows}
      columns={columns}
      height={height}
      empty="No swaps with the neighbours yet."
    />
  );
}

export function ClaimsGrid({ rows, height }: { rows?: ClaimRow[]; height?: number }) {
  const columns: ColDef<ClaimRow>[] = [
    { field: "at", headerName: "When", valueFormatter: when, minWidth: 120, sort: "desc" },
    {
      field: "type",
      headerName: "Problem",
      valueFormatter: (p) => humanize(String(p.value)),
      minWidth: 110,
    },
    { field: "qty", headerName: "Qty", ...right, minWidth: 70 },
    { field: "amount_cents", headerName: "Refund", valueFormatter: cents, ...right, minWidth: 90 },
    { field: "decision", headerName: "Decision", cellRenderer: StatusCell, minWidth: 130 },
    { field: "description", headerName: "Owner said", minWidth: 180, tooltipField: "description" },
    { field: "note", headerName: "Note", minWidth: 180, tooltipField: "note" },
  ];
  return (
    <DataGrid
      rows={rows}
      columns={columns}
      height={height}
      empty="No claims. Everything arrived as ordered."
    />
  );
}

export function QuotesGrid({ rows, height }: { rows?: QuoteRow[]; height?: number }) {
  const columns: ColDef<QuoteRow>[] = [
    {
      field: "week",
      headerName: "Week",
      valueFormatter: (p) => shortDate(`${p.value}T00:00:00+08:00`),
      minWidth: 76,
      maxWidth: 90,
    },
    {
      field: "category",
      headerName: "Category",
      valueFormatter: (p) => CATEGORY_LABEL[p.value] ?? p.value,
      minWidth: 120,
    },
    { field: "round", headerName: "Round", ...right, minWidth: 80, maxWidth: 100 },
    {
      field: "items_total_cents",
      headerName: "Items",
      valueFormatter: cents,
      ...right,
      minWidth: 100,
    },
    {
      field: "delivery_fee_cents",
      headerName: "Delivery",
      valueFormatter: cents,
      ...right,
      minWidth: 90,
    },
    {
      field: "landed_total_cents",
      headerName: "Landed",
      valueFormatter: cents,
      ...right,
      minWidth: 100,
    },
    { field: "status", headerName: "Outcome", cellRenderer: QuoteStatusCell, minWidth: 110 },
    {
      field: "group_order_id",
      headerName: "Order",
      minWidth: 80,
      maxWidth: 90,
      sortable: false,
      cellRenderer: (p: ICellRendererParams) => (
        <Link href={`/orders/${p.value}`} className="text-ink-2 hover:text-ink text-xs font-medium">
          Open
        </Link>
      ),
    },
  ];
  return (
    <DataGrid
      rows={rows}
      columns={columns}
      height={height}
      empty="No quotes yet. Suppliers quote on Tuesday."
      exportName="swarm-quotes"
    />
  );
}
