import { describe, expect, it } from "vitest";

import type { ClaimRow, PaymentRow, ShopDetail, ShopOrderLine, Step, SwapRow } from "@/lib/api";
import { shopWeek } from "@/lib/shop-week";

const WEEK = "2026-10-12";

const shop = {
  name: "Café Mei",
  owner: "Tan Mei Ling",
  limit_cents: 70000,
  report: { week: WEEK, total_saved_cents: 21410, group_saved_cents: 21410 },
  forecast: { note: "Based on your last 4 weeks." },
  approvals: [
    {
      id: "a1",
      kind: "WEEKLY_NEEDS",
      status: "APPROVED",
      question: "…",
      at: "2026-10-12T01:00:00Z",
    },
  ],
} as unknown as ShopDetail;

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
    shop_order_id: "so-dairy",
    ...over,
  };
}

const orders = [
  line({}),
  // Same order, another line: the order's totals are repeated and must be counted once.
  line({
    item: "Eggs (tray of 30)",
    unit: "tray",
    qty_requested: 5,
    qty_delivered: 5,
    unit_price_cents: 775,
    alone_unit_price_cents: 900,
  }),
  line({
    category: "PACKAGING",
    shop_order_id: "so-pack",
    item: "Napkins",
    unit: "pack",
    qty_requested: 7,
    qty_delivered: 7,
    unit_price_cents: 214,
    alone_unit_price_cents: 280,
    hold_cents: 19185,
    captured_cents: 19185,
  }),
  // An older week is none of this week's business.
  line({ week: "2026-10-05", shop_order_id: "so-old", hold_cents: 99999, captured_cents: 99999 }),
];

const pay = (over: Partial<PaymentRow>): PaymentRow =>
  ({
    id: Math.random().toString(36),
    status: "COMPLETED",
    related_type: "shop_order",
    amount_cents: 0,
    at: "",
    ...over,
  }) as PaymentRow;

const payments = [
  pay({ kind: "CAPTURE", amount_cents: 13333, at: "2026-10-15T06:00:00Z" }),
  pay({ kind: "AUTHORIZATION", amount_cents: 14114, at: "2026-10-14T01:00:00Z" }),
];

const swaps = [
  {
    id: "s1",
    kind: "SURPLUS",
    status: "COMPLETED",
    role: "seller",
    seller: { code: "cafe-mei", name: "Café Mei" },
    buyer: { code: "brew-lab", name: "Brew Lab" },
    product_name: "milk",
    unit: "L",
    qty: 8,
    price_cents: 968,
    discount_pct: 35,
    at: "2026-10-16T08:00:00Z",
  },
] as unknown as SwapRow[];

const steps = [
  { key: "negotiation", at: "2026-10-13T02:00:00Z", status: "done" },
  { key: "report", at: "2026-10-18T10:00:00Z", status: "done" },
] as Step[];

describe("a shop's week", () => {
  const week = shopWeek({ shop, orders, payments, swaps, steps, productName: () => "milk" });

  it("counts each order's money once, and only this week's", () => {
    expect(week.money).toEqual({
      heldCents: 14114 + 19185,
      chargedCents: 13333 + 19185,
      releasedCents: 781,
      refundedCents: 0,
      claimedCents: 0,
    });
  });

  it("tells the week in order", () => {
    expect(week.events.map((event) => event.kind)).toEqual([
      "proposal",
      "deal",
      "hold",
      "delivery",
      "swap",
      "report",
    ]);
  });

  it("says what arrived and what that did to the charge", () => {
    const delivery = week.events.find((event) => event.kind === "delivery");
    expect(delivery?.title).toBe(
      "34 of 38 L milk arrived, so PayPal charged S$325.18 and released S$7.81.",
    );
  });

  it("picks the product where buying together helped most", () => {
    const deal = week.events.find((event) => event.kind === "deal");
    expect(deal?.title).toBe("Joined 2 group orders with the neighbours.");
    expect(deal?.detail).toBe("Full cream milk 1L: S$1.86 per L, instead of S$2.45 alone.");
  });

  it("words a neighbour sale from this shop's side", () => {
    const swap = week.events.find((event) => event.kind === "swap");
    expect(swap?.title).toBe("Sold 8 L milk to Brew Lab before it expired: +S$9.68.");
  });

  it("uses the owner's name as given", () => {
    expect(week.events[0].title).toBe(
      "The agent proposed the week's order and Tan Mei Ling approved it.",
    );
  });

  it("has nothing to say before the week starts", () => {
    const empty = shopWeek({
      shop: { ...shop, approvals: [] } as ShopDetail,
      orders: [],
      payments: [],
      swaps: [],
      steps: [],
    });
    expect(empty.events).toEqual([]);
    expect(empty.money.heldCents).toBe(0);
  });

  it("before delivery, money is held and nothing is charged or released", () => {
    const held = shopWeek({
      shop,
      orders: [line({ captured_cents: 0, qty_delivered: null })],
      payments: [payments[1]],
      swaps: [],
      steps: [],
    });
    expect(held.money).toMatchObject({ heldCents: 14114, chargedCents: 0, releasedCents: 0 });
    expect(held.events.map((event) => event.kind)).toEqual(["proposal", "deal", "hold"]);
  });

  const claim = (over: Partial<ClaimRow>): ClaimRow =>
    ({
      id: "c1",
      type: "DAMAGED",
      qty: 2,
      item: "Eggs (tray of 30)",
      what: "2 trays of eggs",
      amount_cents: 1550,
      decision: "ESCALATED_OPERATOR",
      photo_url: null,
      at: "2026-10-15T06:00:00Z",
      ...over,
    }) as ClaimRow;

  it("says what the owner reported and that nothing is refunded while a person decides", () => {
    const open = shopWeek({ shop, orders, payments, swaps, claims: [claim({})], steps });
    const reported = open.events.find((event) => event.kind === "claim");
    expect(reported?.title).toBe("Tan Mei Ling reported 2 trays of eggs damaged.");
    expect(reported?.detail).toBe(
      "No photo came with it, so a person at Swarm decides. S$15.50 is at stake; nothing is refunded yet.",
    );
    expect(open.money.claimedCents).toBe(1550);
    expect(open.events.some((event) => event.kind === "refund")).toBe(false);
    // Straight after the delivery it is about.
    const kinds = open.events.map((event) => event.kind);
    expect(kinds.indexOf("claim")).toBe(kinds.indexOf("delivery") + 1);
  });

  it("follows an upheld claim with PayPal's refund", () => {
    const refund = pay({ kind: "REFUND", amount_cents: 1550, at: "2026-10-18T10:05:00Z" });
    const upheld = shopWeek({
      shop,
      orders,
      payments: [...payments, refund],
      swaps,
      claims: [claim({ decision: "REFUNDED" })],
      steps,
    });
    const kinds = upheld.events.map((event) => event.kind);
    expect(kinds.slice(-2)).toEqual(["report", "refund"]);
    expect(upheld.events.find((event) => event.kind === "claim")?.detail).toBe(
      "Checked and upheld.",
    );
    expect(upheld.events.at(-1)?.title).toBe("PayPal refunded S$15.50 for a claim.");
    expect(upheld.money.claimedCents).toBe(0);
  });

  it("leaves another week's claims and refunds out", () => {
    const old = shopWeek({
      shop,
      orders,
      payments: [
        ...payments,
        pay({ kind: "REFUND", amount_cents: 900, at: "2026-10-08T03:00:00Z" }),
      ],
      swaps,
      claims: [claim({ at: "2026-10-08T02:00:00Z" })],
      steps,
    });
    expect(old.events.some((event) => event.kind === "claim" || event.kind === "refund")).toBe(
      false,
    );
    expect(old.money.claimedCents).toBe(0);
  });
});
