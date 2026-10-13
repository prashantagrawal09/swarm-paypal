import { describe, expect, it } from "vitest";

import type { ShopSummary, Stats } from "@/lib/api";
import {
  chapters,
  duration,
  EMPTY_FRAME,
  type Frame,
  gapAfter,
  isComplete,
  seek,
  step,
} from "@/lib/replay";
import { EMPTY_STREAM, FLIGHT_MS, ingest, type StreamItem } from "@/lib/stream-state";
import { advance, EMPTY_WORLD, shopsAt } from "@/lib/world-state";

// A real recording of the demo week (GET /api/timeline after a fresh run). To refresh it:
// reset, run the week, then save that response here.
import recording from "./fixtures/week.json";

const items = recording.events as unknown as StreamItem[];
const kindOf = (item: StreamItem) => (item.event === "paypal" ? item.data.kind : item.data.type);

function playAll(): Frame {
  let frame = EMPTY_FRAME;
  let now = 1_000_000;
  while (frame.cursor < items.length) {
    now += gapAfter(items[frame.cursor]);
    frame = step(frame, items, now);
  }
  return frame;
}

describe("the recorded week", () => {
  it("is a whole week in order", () => {
    expect(isComplete(items)).toBe(true);
    expect(chapters(items).map((c) => c.step)).toEqual([
      "forecasts",
      "negotiation",
      "holds",
      "delivery",
      "settlement",
      "surplus",
      "emergency",
      "report",
    ]);
    const seqs = items.map((item) => item.seq ?? 0);
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
  });

  it("plays in about the time a live week takes", () => {
    const seconds = duration(items) / 1000;
    expect(seconds).toBeGreaterThan(50);
    expect(seconds).toBeLessThan(110);
  });
});

describe("a week with a claim in it", () => {
  const message = (type: string, from: string, to: string): StreamItem =>
    ({
      event: "agent_message",
      seq: 1,
      data: {
        id: `m-${type}`,
        seq: 1,
        conversation_id: "invoice:g1",
        from,
        to,
        type,
        text: "Bakery Lim reports 2 trays of eggs damaged.",
        payload: { amount_cents: 1550, supplier: "johorfarm", held_back: true },
        at: "2026-10-15T06:00:00+00:00",
      },
    }) as StreamItem;
  const open = message("CLAIM_OPEN", "claims:swarm", "coordinator:swarm");

  it("gives the open claim time to be read, and a line in the story", () => {
    expect(gapAfter(open)).toBeGreaterThan(4 * gapAfter(message("INVOICE", "a", "b")));
    const state = ingest(EMPTY_STREAM, open, 1000);
    expect(state.timeline.map((item) => item.kind === "message" && item.message.type)).toEqual([
      "CLAIM_OPEN",
    ]);
  });
});

describe("the world worked out from events", () => {
  const end = playAll().world;

  it("ends where the server's books ended", () => {
    expect(end.finished).toBe(true);
    expect(end.stats?.saved_cents).toBe(233885);
    expect(end.stats?.books_balanced).toBe(true);
    expect(Object.values(end.steps)).toEqual(Array(8).fill("done"));
    // Money counted event by event agrees with the server's totals.
    expect(end.chargedCents).toBe(end.stats?.captured_cents);
    expect(end.paidOutCents).toBe(end.stats?.payouts_cents);
    expect(end.refundedCents).toBe(end.stats?.refunds_cents);
    expect(end.heldCents).toBe(0);
    expect(end.invoicesRejected).toBe(1);
  });

  it("follows the negotiation: every supplier's quotes only come down, and one wins", () => {
    expect(end.negotiations.map((n) => n.category).sort()).toEqual([
      "DAIRY",
      "PACKAGING",
      "PANTRY",
      "PRODUCE",
    ]);
    for (const negotiation of end.negotiations) {
      expect(negotiation.winner).not.toBeNull();
      const winner = negotiation.trails.find((t) => t.supplier === negotiation.winner);
      expect(winner && winner.landed.length).toBeGreaterThan(0);
      for (const trail of negotiation.trails) {
        const sorted = [...trail.landed].sort((a, b) => b - a);
        expect(trail.landed).toEqual(sorted);
      }
    }
    const dairy = end.negotiations.find((n) => n.category === "DAIRY");
    expect(dairy?.round).toBe(3);
    expect(dairy?.trails.filter((t) => t.declined).length).toBe(1);
  });

  it("counted event by event, the money agrees with the server at the end of every step", () => {
    const ends = items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => item.event === "paypal" && item.data.kind === "step_finished");
    expect(ends).toHaveLength(8);
    for (const { item, index } of ends) {
      // The world just before the step's own totals arrive: nothing but arithmetic on events.
      const counted = seek(EMPTY_FRAME, items, index, 0).world;
      const stats = (item.data as unknown as { stats: Stats }).stats;
      expect(counted.chargedCents).toBe(stats.captured_cents);
      expect(counted.paidOutCents).toBe(stats.payouts_cents);
      expect(counted.refundedCents).toBe(stats.refunds_cents);
      expect(counted.heldCents).toBe(stats.holds_outstanding_cents);
      expect(counted.paypalCalls).toBe(stats.paypal_calls.REAL + stats.paypal_calls.SIMULATED);
      expect(counted.realCalls).toBe(stats.paypal_calls.REAL);
    }
  });

  it("holds money on Wednesday and has charged it once the delivery is settled", () => {
    const marks = chapters(items);
    const at = (stepKey: string) => marks.find((c) => c.step === stepKey)!.index;
    const held = seek(EMPTY_FRAME, items, at("delivery"), 0).world;
    expect(held.heldCents).toBeGreaterThan(300_000);
    expect(held.chargedCents).toBeLessThan(10_000); // only the flash deals so far
    expect(held.steps.holds).toBe("done");
    expect(held.steps.delivery).toBeUndefined();

    const settled = seek(EMPTY_FRAME, items, at("surplus"), 0).world;
    expect(settled.heldCents).toBe(0);
    expect(settled.chargedCents).toBeGreaterThan(300_000);
    // Café Mei got 34 of 38 litres: S$7.81 of its hold went back.
    expect(settled.releasedCents).toBe(781);
  });

  it("gives the map each shop's standing at that moment", () => {
    const shops = [
      { code: "cafe-mei", orders: [{ category: "X", status: "SETTLED" }], pending_approvals: 3 },
      { code: "brew-lab", orders: [], pending_approvals: 0 },
    ] as unknown as ShopSummary[];
    const marks = chapters(items);
    const monday = shopsAt(shops, seek(EMPTY_FRAME, items, marks[1].index, 0).world);
    expect(monday.map((s) => s.orders)).toEqual([[], []]);
    expect(monday[0].pending_approvals).toBe(0);

    const held = shopsAt(shops, seek(EMPTY_FRAME, items, marks[3].index, 0).world);
    expect(held[0].orders.length).toBeGreaterThan(0);
    expect(new Set(held[0].orders.map((o) => o.status))).toEqual(new Set(["AUTHORIZED"]));

    const done = shopsAt(shops, end);
    expect(done.every((s) => s.orders.every((o) => o.status === "CAPTURED"))).toBe(true);
  });

  it("counts calls to the real sandbox apart from simulated ones", () => {
    const real: StreamItem = {
      event: "paypal",
      data: { kind: "hold_placed", at: "", shop: "cafe-mei", amount_cents: 1000, mode: "REAL" },
    };
    const simulated: StreamItem = {
      event: "paypal",
      data: { kind: "swap_completed", at: "", amount_cents: 500, mode: "SIMULATED" },
    };
    const world = advance(advance(EMPTY_WORLD, real), simulated);
    expect(world.paypalCalls).toBe(3);
    expect(world.realCalls).toBe(1);
  });

  it("starts over on a reset", () => {
    const reset: StreamItem = { event: "paypal", data: { kind: "reset", at: "" } };
    expect(advance(end, reset)).toEqual(EMPTY_WORLD);
  });
});

describe("the stream state", () => {
  it("jumping ahead lands on the same messages and events as playing, without motion", () => {
    const played = playAll();
    const jumped = seek(EMPTY_FRAME, items, items.length, 5);
    expect(jumped.cursor).toBe(items.length);
    expect(jumped.stream.messages.map((m) => m.id)).toEqual(
      played.stream.messages.map((m) => m.id),
    );
    expect(jumped.stream.events.map((e) => e.kind)).toEqual(
      played.stream.events.map((e) => e.kind),
    );
    expect(jumped.world).toEqual(played.world);
    expect(jumped.stream.flights).toEqual([]);
    expect(jumped.stream.activity).toEqual({});
    expect(played.stream.flights.length).toBeGreaterThan(0);
  });

  it("seeking backwards replays from the start", () => {
    const marks = chapters(items);
    const late = seek(EMPTY_FRAME, items, marks[5].index, 0);
    const early = seek(late, items, marks[2].index, 0);
    expect(early.cursor).toBe(marks[2].index);
    expect(early.world).toEqual(seek(EMPTY_FRAME, items, marks[2].index, 0).world);
  });

  it("draws a flight for agent-to-agent messages and for money, not for owner chats", () => {
    const first = (predicate: (item: StreamItem) => boolean) => items.find(predicate)!;
    const rfq = first((i) => kindOf(i) === "RFQ");
    const hold = first((i) => kindOf(i) === "hold_placed");
    const owner = first((i) => i.event === "agent_message" && i.data.to.startsWith("owner:"));

    let state = ingest(EMPTY_STREAM, rfq, 1000);
    expect(state.flights).toMatchObject([{ from: "hub", to: "supplier:*", kind: "message" }]);
    state = ingest(state, hold, 1010);
    expect(state.flights[1]).toMatchObject({ to: "hub", kind: "hold", delay: 45 });
    state = ingest(state, owner, 1020);
    expect(state.flights).toHaveLength(2);
    // Old flights leave when something new takes off.
    state = ingest(state, hold, 1020 + FLIGHT_MS + 500);
    expect(state.flights).toHaveLength(1);
  });

  it("never applies the same message twice, and a reset clears everything", () => {
    const message = items.find((i) => i.event === "agent_message")!;
    const once = ingest(EMPTY_STREAM, message, 1);
    expect(ingest(once, message, 2)).toBe(once);
    const cleared = ingest(once, { event: "paypal", data: { kind: "reset", at: "" } }, 3);
    expect(cleared.messages).toEqual([]);
    expect(cleared.timeline).toEqual([]);
  });

  it("keeps the story to what matters: steps, short deliveries, rejections, the summary", () => {
    const { stream } = playAll();
    const told = stream.timeline.map((line) =>
      line.kind === "event" ? line.event.kind : line.message.type,
    );
    expect(told[0]).toBe("week_summary");
    const everything = items.filter((i) => kindOf(i) === "captured");
    const partial = everything.filter((i) => i.event === "paypal" && i.data.partial);
    expect(everything.length).toBe(40);
    expect(partial.length).toBeGreaterThan(0);
    expect(partial.length).toBeLessThan(5);
  });
});
