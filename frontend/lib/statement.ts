/**
 * A shop's weekly statement: the lines it was charged for, order by order, adding up
 * exactly to what PayPal charged. Pure.
 */

import type { ShopOrderLine } from "@/lib/api";

export type StatementOrder = {
  id: string;
  category: string;
  supplier: string | null;
  lines: ShopOrderLine[];
  goodsCents: number;
  /** This shop's share of the one delivery, for what arrived. */
  deliveryCents: number;
  heldCents: number;
  chargedCents: number;
  releasedCents: number;
  refundedCents: number;
  /** False while the order is held but not yet charged. */
  charged: boolean;
};

export type Statement = {
  orders: StatementOrder[];
  heldCents: number;
  chargedCents: number;
  releasedCents: number;
  refundedCents: number;
  /** What the same goods would have cost bought alone, at each shop's own price tier. */
  aloneGoodsCents: number;
  goodsCents: number;
};

/** This week's orders for one shop, grouped and totalled. */
export function statement(lines: ShopOrderLine[], week: string): Statement {
  const byOrder = new Map<string, ShopOrderLine[]>();
  for (const line of lines) {
    if (line.week !== week) continue;
    byOrder.set(line.shop_order_id, [...(byOrder.get(line.shop_order_id) ?? []), line]);
  }
  const orders: StatementOrder[] = [...byOrder.entries()].map(([id, own]) => {
    const first = own[0];
    const charged = first.captured_cents > 0;
    // Before delivery a line's total is for what was ordered; afterwards, for what arrived.
    const goodsCents = own.reduce((sum, line) => sum + line.line_total_cents, 0);
    return {
      id,
      category: first.category,
      supplier: first.supplier,
      lines: own,
      goodsCents,
      // Whatever the charge holds beyond the goods is the delivery share.
      deliveryCents: charged
        ? Math.max(0, first.captured_cents - goodsCents)
        : first.delivery_share_cents,
      heldCents: first.hold_cents,
      chargedCents: first.captured_cents,
      releasedCents: charged ? first.hold_cents - first.captured_cents : 0,
      refundedCents: first.refunded_cents,
      charged,
    };
  });
  orders.sort((a, b) => a.category.localeCompare(b.category));
  const sum = (pick: (order: StatementOrder) => number) =>
    orders.reduce((total, order) => total + pick(order), 0);
  const delivered = (line: ShopOrderLine) => line.qty_delivered ?? line.qty_requested;
  return {
    orders,
    heldCents: sum((o) => o.heldCents),
    chargedCents: sum((o) => o.chargedCents),
    releasedCents: sum((o) => o.releasedCents),
    refundedCents: sum((o) => o.refundedCents),
    goodsCents: sum((o) => o.goodsCents),
    aloneGoodsCents: orders
      .flatMap((order) => order.lines)
      .reduce((total, line) => total + delivered(line) * (line.alone_unit_price_cents ?? 0), 0),
  };
}
