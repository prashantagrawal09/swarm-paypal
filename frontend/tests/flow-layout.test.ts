import { describe, expect, it } from "vitest";

import type { MoneyFlow } from "@/lib/api";
import { layoutFlow, sinks, spread } from "@/lib/flow-layout";

const flow: MoneyFlow = {
  week: "2026-10-12",
  charged_cents: 499380,
  suppliers_cents: 487611,
  neighbours_cents: 1820,
  refunds_cents: 0,
  fee_cents: 9949,
  owed_cents: 0,
  held_cents: 0,
  shops: [
    {
      code: "kopi-corner",
      name: "Kopi Corner",
      mode: "SIMULATED",
      charged_cents: 199380,
      refunded_cents: 0,
      received_cents: 0,
    },
    {
      code: "cafe-mei",
      name: "Café Mei",
      mode: "SIMULATED",
      charged_cents: 300000,
      refunded_cents: 0,
      received_cents: 968,
    },
    {
      code: "idle",
      name: "Idle Shop",
      mode: "SIMULATED",
      charged_cents: 0,
      refunded_cents: 0,
      received_cents: 852,
    },
  ],
  suppliers: [
    { code: "packpro", name: "PackPro", mode: "SIMULATED", paid_cents: 185083 },
    { code: "johorfarm", name: "Johor Farm Fresh", mode: "SIMULATED", paid_cents: 302528 },
  ],
};
const margin = { left: 160, right: 190, top: 30, bottom: 10 };

describe("sinks", () => {
  it("lists suppliers by code, then the rest, and drops empty ones", () => {
    expect(sinks(flow).map((s) => s.id)).toEqual([
      "supplier:johorfarm",
      "supplier:packpro",
      "neighbours",
      "fee",
    ]);
  });

  it("keeps each supplier's own colour", () => {
    const [johor, packpro] = sinks(flow);
    expect(johor.color).toBe("var(--s2)");
    expect(packpro.color).toBe("var(--s3)");
  });
});

describe("layoutFlow", () => {
  const layout = layoutFlow(flow, 900, 440, margin);

  it("conserves money: what flows in equals what flows out", () => {
    const into = layout.links.filter((l) => l.to === "mid").reduce((s, l) => s + l.value, 0);
    const out = layout.links.filter((l) => l.from === "mid").reduce((s, l) => s + l.value, 0);
    expect(into).toBe(flow.charged_cents);
    expect(out).toBe(flow.charged_cents);
    expect(layout.total).toBe(flow.charged_cents);
  });

  it("orders shops by what they were charged and skips shops that paid nothing", () => {
    const left = layout.nodes.filter((n) => n.side === "left");
    expect(left.map((n) => n.id)).toEqual(["shop:cafe-mei", "shop:kopi-corner"]);
    expect(left[0].h).toBeGreaterThan(left[1].h);
  });

  it("uses one scale, so the middle bar is as tall as everything through it", () => {
    const mid = layout.nodes.find((n) => n.id === "mid")!;
    const left = layout.nodes.filter((n) => n.side === "left");
    expect(mid.h).toBeCloseTo(
      left.reduce((sum, n) => sum + n.h, 0),
      5,
    );
    expect(mid.y).toBeGreaterThanOrEqual(margin.top);
    expect(mid.y + mid.h).toBeLessThanOrEqual(440 - margin.bottom + 0.001);
  });

  it("keeps labels apart even for hairline flows", () => {
    const right = layout.nodes.filter((n) => n.side === "right");
    for (let i = 1; i < right.length; i++) {
      expect(right[i].labelY - right[i - 1].labelY).toBeGreaterThanOrEqual(15 - 0.001);
    }
  });

  it("returns nothing to draw before any money has moved", () => {
    const empty = { ...flow, shops: flow.shops.map((s) => ({ ...s, charged_cents: 0 })) };
    expect(layoutFlow(empty, 900, 440, margin)).toEqual({ nodes: [], links: [], total: 0 });
  });
});

describe("spread", () => {
  it("pushes close labels apart, top to bottom", () => {
    expect(spread([10, 12, 13], 15, 400)).toEqual([10, 25, 40]);
  });

  it("pulls the tail back up when it would fall off the bottom", () => {
    expect(spread([380, 385, 390], 15, 400)).toEqual([370, 385, 400]);
  });

  it("leaves well-spaced labels alone", () => {
    expect(spread([10, 60, 200], 15, 400)).toEqual([10, 60, 200]);
  });
});
