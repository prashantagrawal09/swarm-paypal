/**
 * What a replay shows in place of the server's own view of the week: the same overview,
 * with the steps and totals as they stood at the replayed moment. Pure.
 */

import type { Overview, Stats } from "@/lib/api";
import type { LiveState } from "@/lib/live";
import type { StreamState } from "@/lib/stream-state";
import type { World } from "@/lib/world-state";

export const NO_STATS: Stats = {
  saved_cents: 0,
  negotiation_saved_cents: 0,
  food_saved_grams: 0,
  captured_cents: 0,
  payouts_cents: 0,
  refunds_cents: 0,
  holds_outstanding_cents: 0,
  fees_cents: 0,
  paypal_calls: { REAL: 0, SIMULATED: 0 },
  books_balanced: true,
  shops: 12,
  delivered_lines: 0,
};

/** The overview as of the replayed moment: steps done so far, then one "next". */
export function stageOverview(overview: Overview, world: World, running: boolean): Overview {
  let nextSeen = false;
  return {
    ...overview,
    running,
    stats: world.stats ?? NO_STATS,
    steps: overview.steps.map((step) => {
      if (world.steps[step.key] === "done") return { ...step, status: "done" as const };
      if (nextSeen) return { ...step, status: "pending" as const };
      nextSeen = true;
      return { ...step, status: "next" as const };
    }),
  };
}

/** A replayed stream in the shape the live components read. */
export function stageLive(stream: StreamState): LiveState {
  return {
    connected: true,
    started: true,
    seeded: true,
    messages: stream.messages,
    events: stream.events,
    activity: stream.activity,
    arcs: stream.arcs,
    flights: stream.flights,
    timeline: stream.timeline,
    lastAward: stream.lastAward,
  };
}
