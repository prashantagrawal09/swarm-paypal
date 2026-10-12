import { describe, expect, it } from "vitest";

import { type GroupOrder, keyFromHash, type PaymentRow } from "@/lib/api";
import { moneyFlight, nodeOf } from "@/lib/flights";
import { BAND, H, PAD, PIN, W, curve, project, relax } from "@/lib/map-geometry";
import { lanes } from "@/lib/negotiation";
import { paymentEvent } from "@/lib/payment-events";
import { matches } from "@/lib/search";
import { isLocalUrl, wakeProgress } from "@/lib/server-status";
import { niceTicks, thin } from "@/lib/ticks";

describe("map geometry", () => {
  it("projects the estate inside the canvas, north at the top", () => {
    const [x1, north] = project(1.28603, 103.83062); // Little Pasta, near Tiong Bahru Road
    const [x2, south] = project(1.28301, 103.82962); // Green Bowl, on Eng Hoon Street
    expect(north).toBeLessThan(south);
    expect(x2).toBeLessThan(x1);
    for (const [x, y] of [
      [x1, north],
      [x2, south],
    ]) {
      expect(x).toBeGreaterThan(PAD - 1);
      expect(x).toBeLessThan(W - PAD + 1);
      expect(y).toBeGreaterThan(BAND);
      expect(y).toBeLessThan(H);
    }
  });

  it("separates the market stalls that share a building", () => {
    const stalls = [
      { code: "uncle-tan-noodles", ...xy(1.28522, 103.83221) },
      { code: "nasi-lemak-hub", ...xy(1.28503, 103.83244) },
      { code: "cafe-mei", ...xy(1.28512, 103.83262) },
    ];
    const placed = Object.values(relax(stalls));
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const d = Math.hypot(placed[i][0] - placed[j][0], placed[i][1] - placed[j][1]);
        expect(d).toBeGreaterThanOrEqual(PIN * 2 + 4 - 0.5);
      }
    }
  });

  it("is deterministic and leaves distant pins where they are", () => {
    const far = [
      { code: "a", x: 100, y: 100 },
      { code: "b", x: 400, y: 300 },
    ];
    expect(relax(far)).toEqual({ a: [100, 100], b: [400, 300] });
    expect(relax(far)).toEqual(relax(far));
  });

  it("draws a curved path that starts and ends on its nodes", () => {
    const d = curve([10, 20], [110, 20]);
    expect(d.startsWith("M10.0,20.0 Q")).toBe(true);
    expect(d.endsWith(" 110.0,20.0")).toBe(true);
    expect(d).not.toContain("Q60.0,20.0"); // bowed, not straight
  });

  function xy(lat: number, lng: number) {
    const [x, y] = project(lat, lng);
    return { x, y };
  }
});

describe("flights", () => {
  it("maps agents to map nodes, and owners to none", () => {
    expect(nodeOf("shop:cafe-mei")).toBe("shop:cafe-mei");
    expect(nodeOf("supplier:packpro")).toBe("supplier:packpro");
    expect(nodeOf("coordinator:swarm")).toBe("hub");
    expect(nodeOf("claims:swarm")).toBe("hub");
    expect(nodeOf("suppliers:all")).toBe("supplier:*");
    expect(nodeOf("shops:all")).toBe("shop:*");
    expect(nodeOf("owner:cafe-mei")).toBeNull();
  });

  it("sends money the right way round", () => {
    const at = "2026-10-14T01:00:00+00:00";
    expect(moneyFlight({ id: "1", at, kind: "hold_placed", shop: "cafe-mei" })).toEqual([
      "shop:cafe-mei",
      "hub",
      "hold",
    ]);
    expect(moneyFlight({ id: "2", at, kind: "supplier_paid", supplier: "packpro" })).toEqual([
      "hub",
      "supplier:packpro",
      "payout",
    ]);
    expect(moneyFlight({ id: "3", at, kind: "refunded", shop: "cafe-mei" })).toEqual([
      "hub",
      "shop:cafe-mei",
      "refund",
    ]);
    expect(
      moneyFlight({ id: "4", at, kind: "swap_completed", buyer: "brew-lab", seller: "cafe-mei" }),
    ).toEqual(["shop:brew-lab", "shop:cafe-mei", "charge"]);
    expect(moneyFlight({ id: "5", at, kind: "invoice_sent", supplier: "packpro" })).toBeNull();
  });
});

describe("negotiation lanes", () => {
  it("keeps each supplier's opening and latest quote", () => {
    const group = {
      quotes: [
        {
          supplier: "johorfarm",
          supplier_name: "Johor Farm Fresh",
          round: 2,
          landed_cents: 195378,
          status: "SUPERSEDED",
        },
        {
          supplier: "freshdairy",
          supplier_name: "FreshDairy SG",
          round: 1,
          landed_cents: 206149,
          status: "SUPERSEDED",
        },
        {
          supplier: "johorfarm",
          supplier_name: "Johor Farm Fresh",
          round: 1,
          landed_cents: 198103,
          status: "SUPERSEDED",
        },
        {
          supplier: "johorfarm",
          supplier_name: "Johor Farm Fresh",
          round: 3,
          landed_cents: 192974,
          status: "AWARDED",
        },
      ],
    } as unknown as GroupOrder;
    expect(lanes(group)).toEqual([
      { code: "freshdairy", name: "FreshDairy SG", opening: 206149, latest: 206149, round: 1 },
      { code: "johorfarm", name: "Johor Farm Fresh", opening: 198103, latest: 192974, round: 3 },
    ]);
  });
});

describe("payment history as feed events", () => {
  const row = (extra: Partial<PaymentRow>): PaymentRow => ({
    id: "p1",
    kind: "CAPTURE",
    status: "COMPLETED",
    mode: "SIMULATED",
    amount_cents: 13333,
    currency: "SGD",
    paypal_id: "SIM-CAP-1",
    related_type: "shop_order",
    related_id: "x",
    shop: { code: "cafe-mei", name: "Café Mei" },
    supplier: null,
    error: null,
    at: "2026-10-15T06:00:00+00:00",
    ...extra,
  });

  it("names each kind of payment", () => {
    expect(paymentEvent(row({}))?.kind).toBe("captured");
    expect(paymentEvent(row({ related_type: "flash_deal" }))?.kind).toBe("flash_deal_bought");
    expect(paymentEvent(row({ kind: "AUTHORIZATION" }))?.kind).toBe("hold_placed");
    expect(paymentEvent(row({ kind: "PAYOUT", related_type: "swap" }))?.kind).toBe("swap_payout");
    expect(paymentEvent(row({ kind: "PAYOUT", related_type: "group_order" }))?.kind).toBe(
      "supplier_paid",
    );
  });

  it("shows failures as failures and hides calls still in flight", () => {
    expect(
      paymentEvent(row({ kind: "AUTHORIZATION", status: "FAILED", error: "declined" })),
    ).toMatchObject({
      kind: "hold_failed",
      reason: "declined",
    });
    expect(paymentEvent(row({ status: "PENDING" }))).toBeNull();
  });
});

describe("search and ticks", () => {
  it("matches every word, in any field, in any case", () => {
    expect(matches("kopi", "Kopi Corner", "Rahim bin Osman · kopitiam")).toBe(true);
    expect(matches("corner rahim", "Kopi Corner", "Rahim bin Osman · kopitiam")).toBe(true);
    expect(matches("corner mei", "Kopi Corner", "Rahim bin Osman")).toBe(false);
    expect(matches("", "anything")).toBe(true);
  });

  it("picks round tick values inside the range", () => {
    const ticks = niceTicks(180, 250, 4);
    expect(ticks.every((t) => t >= 180 && t <= 250)).toBe(true);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    expect(niceTicks(5, 5, 4)).toEqual([5]);
  });

  it("drops tick labels that would collide", () => {
    expect(thin([{ x: 0 }, { x: 10 }, { x: 40 }, { x: 55 }, { x: 90 }], 30)).toEqual([
      { x: 0 },
      { x: 40 },
      { x: 90 },
    ]);
  });
});

describe("demo key in a shared link", () => {
  it("reads the key from the fragment", () => {
    expect(keyFromHash("#key=judges-2026")).toBe("judges-2026");
    expect(keyFromHash("#tab=money&key=%20abc%20")).toBe("abc");
  });

  it("ignores fragments without a usable key", () => {
    expect(keyFromHash("")).toBeNull();
    expect(keyFromHash("#section")).toBeNull();
    expect(keyFromHash("#key=")).toBeNull();
    expect(keyFromHash("#key=%20")).toBeNull();
  });
});

describe("waking a sleeping server", () => {
  it("tells a laptop API from a hosted one", () => {
    expect(isLocalUrl("http://localhost:8000")).toBe(true);
    expect(isLocalUrl("http://127.0.0.1:8000")).toBe(true);
    expect(isLocalUrl("https://swarm-api.onrender.com")).toBe(false);
    expect(isLocalUrl("https://localhost.example.com")).toBe(false);
    expect(isLocalUrl("not a url")).toBe(false);
  });

  it("progress only moves forward and never claims to be finished", () => {
    const samples = [0, 1000, 5000, 20_000, 50_000, 120_000, 600_000].map((ms) => wakeProgress(ms));
    expect(samples[0]).toBe(0);
    for (let i = 1; i < samples.length; i++) {
      expect(samples[i]).toBeGreaterThanOrEqual(samples[i - 1]);
    }
    expect(wakeProgress(5000)).toBeGreaterThan(0.15); // visibly moving within seconds
    expect(wakeProgress(600_000)).toBeLessThan(1);
  });
});
