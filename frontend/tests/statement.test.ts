import { describe, expect, it } from "vitest";

import type { ShopOrderLine } from "@/lib/api";
import { statement } from "@/lib/statement";

const WEEK = "2026-10-12";

function line(over: Partial<ShopOrderLine>): ShopOrderLine {
  return {
    id: Math.random().toString(36),
    week: WEEK,
    category: "DAIRY",
    supplier: "Johor Farm Fresh",
    item: "Full cream milk 1L",
    brand: "Farm Gold",
    product: "milk-full-cream-1l",
    unit: "L",
    qty_requested: 38,
    qty_delivered: 34,
    unit_price_cents: 186,
    alone_unit_price_cents: 245,
    line_total_cents: 6324,
    order_status: "SETTLED",
    group_status: "SETTLED",
    hold_cents: 14114,
    captured_cents: 13333,
    refunded_cents: 0,
    delivery_share_cents: 448,
    shop_order_id: "dairy",
    ...over,
  };
}

// Café Mei's dairy order in the demo week: three lines, one of them short.
const dairy = [
  line({}),
  line({
    item: "Butter 250g",
    unit: "block",
    qty_requested: 7,
    qty_delivered: 7,
    unit_price_cents: 389,
    alone_unit_price_cents: 470,
    line_total_cents: 2723,
  }),
  line({
    item: "Eggs (tray of 30)",
    unit: "tray",
    qty_requested: 5,
    qty_delivered: 5,
    unit_price_cents: 775,
    alone_unit_price_cents: 900,
    line_total_cents: 3875,
  }),
];

describe("a shop's weekly statement", () => {
  it("adds up to exactly what PayPal charged, with delivery as the remainder", () => {
    const result = statement(dairy, WEEK);
    const [order] = result.orders;
    expect(order.goodsCents).toBe(6324 + 2723 + 3875);
    expect(order.goodsCents + order.deliveryCents).toBe(order.chargedCents);
    expect(order.deliveryCents).toBe(411);
    expect(order.releasedCents).toBe(781);
    expect(result.chargedCents).toBe(13333);
    expect(result.heldCents - result.chargedCents).toBe(result.releasedCents);
  });

  it("prices 'alone' for what actually arrived", () => {
    const result = statement(dairy, WEEK);
    expect(result.aloneGoodsCents).toBe(34 * 245 + 7 * 470 + 5 * 900);
    expect(result.aloneGoodsCents).toBeGreaterThan(result.goodsCents);
  });

  it("keeps orders apart, leaves other weeks out, and waits for delivery before charging", () => {
    const held = line({
      shop_order_id: "pack",
      category: "PACKAGING",
      captured_cents: 0,
      qty_delivered: null,
      hold_cents: 19185,
      line_total_cents: 18760,
      delivery_share_cents: 425,
    });
    const old = line({ week: "2026-10-05", shop_order_id: "old" });
    const result = statement([...dairy, held, old], WEEK);
    expect(result.orders.map((order) => order.id)).toEqual(["dairy", "pack"]);
    const pack = result.orders[1];
    expect(pack.charged).toBe(false);
    expect(pack.releasedCents).toBe(0);
    expect(pack.deliveryCents).toBe(425);
    expect(result.heldCents).toBe(14114 + 19185);
    expect(result.chargedCents).toBe(13333);
  });

  it("is empty before the week has any orders", () => {
    expect(statement([], WEEK)).toMatchObject({ orders: [], heldCents: 0, chargedCents: 0 });
  });
});
