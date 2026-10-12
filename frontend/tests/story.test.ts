import { describe, expect, it } from "vitest";

import type { Overview, Step } from "@/lib/api";
import type { StoryItem } from "@/lib/live";
import { currentCaption, describeStory, restingCaption } from "@/lib/story";

const names = { "cafe-mei": "Café Mei", "brew-lab": "Brew Lab", johorfarm: "Johor Farm Fresh" };

const steps: Step[] = [
  ["forecasts", "Monday: forecasts", "Each shop agent proposes next week's order; owners approve"],
  [
    "negotiation",
    "Tuesday: negotiation",
    "Twelve orders become one; three supplier agents compete",
  ],
  ["holds", "Wednesday: PayPal holds", "Money is reserved on every shop's PayPal, not taken"],
].map(([key, title, description]) => ({
  key,
  title,
  description,
  at: "2026-10-12T01:00:00+00:00",
  status: "pending" as const,
}));

const event = (kind: string, extra: Record<string, unknown> = {}): StoryItem => ({
  id: `st-${kind}`,
  seenAt: 0,
  kind: "event",
  event: { id: `ev-${kind}`, kind, at: "2026-10-15T00:00:00+00:00", ...extra },
});

function overview(statuses: Step["status"][], running = false): Overview {
  return {
    now: "",
    local: "Mon 12 Oct, 08:00",
    day: "MON",
    phase: "",
    week: "2026-10-12",
    steps: steps.map((s, i) => ({ ...s, status: statuses[i] })),
    running,
    scenario: {},
    modes: { shops: {}, suppliers: {} },
    llm: { provider: "offline", model: null },
    paypal_env: "sandbox",
    telegram: false,
    demo_mode: true,
    log: [],
    stats: {
      saved_cents: 233885,
      negotiation_saved_cents: 13429,
      food_saved_grams: 8400,
      captured_cents: 0,
      payouts_cents: 0,
      refunds_cents: 0,
      holds_outstanding_cents: 0,
      fees_cents: 0,
      paypal_calls: { REAL: 0, SIMULATED: 94 },
      books_balanced: true,
      shops: 12,
      delivered_lines: 0,
    },
  };
}

describe("describeStory", () => {
  it("explains a step from its description", () => {
    const caption = describeStory(event("step_started", { step: "holds" }), names, steps);
    expect(caption).toMatchObject({
      title: "Wednesday: PayPal holds",
      detail: "Money is reserved on every shop's PayPal, not taken.",
      step: "holds",
    });
  });

  it("only narrates short deliveries, not routine charges", () => {
    const routine = event("captured", { shop: "cafe-mei", amount_cents: 14114, partial: false });
    expect(describeStory(routine, names, steps)).toBeNull();
    const short = event("captured", {
      shop: "cafe-mei",
      amount_cents: 13333,
      hold_cents: 14114,
      partial: true,
    });
    const caption = describeStory(short, names, steps);
    expect(caption?.title).toBe("Café Mei got a short delivery, so PayPal charges only S$133.33.");
    expect(caption?.detail).toContain("S$141.14 was held");
    expect(caption?.tone).toBe("warning");
  });

  it("makes a rejected invoice loud and an approved one calm", () => {
    const rejected = describeStory(
      event("invoice_checked", {
        supplier: "johorfarm",
        invoice_number: "SW26W42-DAI-R1",
        approved: false,
        overcharge_cents: 6900,
      }),
      names,
      steps,
    );
    expect(rejected?.tone).toBe("critical");
    expect(rejected?.title).toBe("Invoice rejected: Johor Farm Fresh overcharged S$69.00.");
    const approved = describeStory(
      event("invoice_checked", { supplier: "johorfarm", approved: true, amount_cents: 178794 }),
      names,
      steps,
    );
    expect(approved?.tone).toBe("good");
  });

  it("names both neighbours in a swap", () => {
    const caption = describeStory(
      event("swap_completed", { seller: "cafe-mei", buyer: "brew-lab", amount_cents: 968 }),
      names,
      steps,
    );
    expect(caption?.title).toBe("Café Mei helps Brew Lab: S$9.68, paid on the spot.");
  });

  it("falls back to the code for a shop it has no name for", () => {
    const caption = describeStory(
      event("refunded", { shop: "new-shop", amount_cents: 500 }),
      {},
      steps,
    );
    expect(caption?.title).toBe("new-shop is refunded S$5.00.");
  });

  it("uses the coordinator's own words for an award", () => {
    const item: StoryItem = {
      id: "st-m1",
      seenAt: 0,
      kind: "message",
      message: {
        id: "m1",
        seq: 1,
        conversation_id: "negotiation:2026-10-12:dairy",
        from: "coordinator:swarm",
        to: "shops:all",
        type: "AWARD_SUMMARY",
        text: "Dairy this week: Johor Farm Fresh, S$1,845.97 landed for the group.",
        payload: {},
        at: "",
      },
    };
    expect(describeStory(item, names, steps)).toMatchObject({
      title: "Dairy this week: Johor Farm Fresh, S$1,845.97 landed for the group.",
      tone: "good",
    });
  });

  it("ignores events it has nothing to say about", () => {
    expect(describeStory(event("demo_action"), names, steps)).toBeNull();
  });
});

describe("resting and current captions", () => {
  it("invites a start before the week begins", () => {
    expect(restingCaption(overview(["next", "pending", "pending"])).title).toContain(
      "Monday morning",
    );
  });

  it("says what is next mid-week, and sums up at the end", () => {
    expect(restingCaption(overview(["done", "next", "pending"])).title).toBe(
      "Up next: Tuesday: negotiation",
    );
    const end = restingCaption(overview(["done", "done", "done"]));
    expect(end.title).toBe("Week complete: S$2,339 saved across the street.");
    expect(end.detail).toContain("S$134.29 of it won by negotiating");
  });

  it("prefers the newest thing worth saying over the resting caption", () => {
    const timeline = [
      event("captured", { shop: "cafe-mei", partial: false }), // newest, but routine
      event("refunded", { shop: "cafe-mei", amount_cents: 781 }),
    ];
    const current = currentCaption(timeline, names, overview(["done", "next", "pending"]));
    expect(current.caption.title).toBe("Café Mei is refunded S$7.81.");
    expect(current.id).toBe("st-refunded");
    expect(currentCaption([], names, overview(["done", "next", "pending"])).id).toMatch(/^rest-/);
  });
});
