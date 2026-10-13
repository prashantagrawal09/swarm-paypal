/**
 * What the live stream adds up to: the recent agent messages and PayPal events, a flight on
 * the map for each, the week's story for the narrator, and who was just active. One pure
 * step function, used both for the live connection and for replaying a recorded week.
 */

import type { AgentMessage } from "@/lib/api";
import { moneyFlight, nodeOf } from "@/lib/flights";

/** A PayPal (or week) event as the server sends it. */
export type PayPalEventData = {
  kind: string;
  at: string;
  shop?: string;
  supplier?: string;
  buyer?: string;
  seller?: string;
  amount_cents?: number;
  gross_cents?: number;
  paypal_id?: string;
  payout_paypal_id?: string;
  capture_paypal_id?: string;
  mode?: "REAL" | "SIMULATED";
  category?: string;
  partial?: boolean;
  hold_cents?: number;
  reason?: string;
  step?: string;
  title?: string;
  [key: string]: unknown;
};

/** The same event once this browser has given it an ID (for lists and the story). */
export type PayPalEvent = PayPalEventData & { id: string };

/** One thing the server sent: an agent message or a PayPal event, as it came off the wire. */
export type StreamItem =
  | { event: "agent_message"; data: AgentMessage; seq?: number }
  | { event: "paypal"; data: PayPalEventData; seq?: number };

export type Arc = { id: string; from: string; to: string; kind: string; at: number };

/**
 * Something travelling between two agents on the map. Ends are node tokens: `shop:<code>`,
 * `supplier:<code>`, `hub` (the coordinator and Swarm's PayPal balance), or the broadcasts
 * `shop:*` / `supplier:*`.
 */
export type FlightKind = "message" | "hold" | "charge" | "payout" | "refund";
export type Flight = {
  id: string;
  from: string;
  to: string;
  kind: FlightKind;
  at: number;
  /** Milliseconds to wait before taking off, so a burst fans out instead of overlapping. */
  delay: number;
};

/** One line of the week's story, newest first in `timeline`. */
export type StoryItem = { id: string; /** When this browser saw it (ms). */ seenAt: number } & (
  { kind: "event"; event: PayPalEvent } | { kind: "message"; message: AgentMessage }
);

export type StreamState = {
  messages: AgentMessage[];
  events: PayPalEvent[];
  /** Last activity per shop code, supplier code, or "hub". */
  activity: Record<string, { at: number; kind: string }>;
  arcs: Arc[];
  flights: Flight[];
  timeline: StoryItem[];
  /** The negotiation that was just awarded (for the spotlight). */
  lastAward: { conversation: string; at: number } | null;
  /** IDs handed out so far. */
  serial: { event: number; flight: number };
  /** The burst being fanned out: things that arrive together take off one after another. */
  burst: { at: number; index: number };
};

export const EMPTY_STREAM: StreamState = {
  messages: [],
  events: [],
  activity: {},
  arcs: [],
  flights: [],
  timeline: [],
  lastAward: null,
  serial: { event: 0, flight: 0 },
  burst: { at: 0, index: 0 },
};

// A whole week of messages (about 300), so the feed's filters reach back to Monday.
export const MAX_MESSAGES = 500;
export const MAX_EVENTS = 80;
export const MAX_FLIGHTS = 70;
export const MAX_STORY = 40;
export const FLIGHT_MS = 2600;
const BURST_WINDOW_MS = 150;
const BURST_STEP_MS = 45;
const BURST_MAX_MS = 1100;
const ARC_MS = 8000;

/** Agent messages that move the week's story forward (the narrator shows these). */
const STORY_MESSAGES = new Set(["RFQ", "FINAL_CALL", "AWARD_SUMMARY", "NO_AWARD", "FLASH_DEAL"]);
const STORY_EVENTS = new Set([
  "step_started",
  "captured",
  "refunded",
  "supplier_paid",
  "swap_completed",
  "flash_deal_bought",
  "invoice_checked",
  "approval_needed",
  "hold_failed",
  "week_summary",
]);

/** The map node (shop code, supplier code or "hub") an agent ID lights up. */
function activityCode(agent: string): string | undefined {
  const [kind, code] = agent.split(":");
  if (kind === "shop" || kind === "owner" || kind === "supplier") return code;
  return kind === "coordinator" || kind === "claims" ? "hub" : undefined;
}

function touched(
  activity: StreamState["activity"],
  codes: (string | undefined)[],
  kind: string,
  now: number,
): StreamState["activity"] {
  const next = { ...activity };
  for (const code of codes) if (code) next[code] = { at: now, kind };
  return next;
}

function launched(
  state: StreamState,
  from: string,
  to: string,
  kind: FlightKind,
  now: number,
): Pick<StreamState, "flights" | "burst" | "serial"> {
  const burst =
    now - state.burst.at < BURST_WINDOW_MS
      ? { at: now, index: state.burst.index + 1 }
      : { at: now, index: 0 };
  const serial = { ...state.serial, flight: state.serial.flight + 1 };
  const flight: Flight = {
    id: `fl-${serial.flight}`,
    from,
    to,
    kind,
    at: now,
    delay: Math.min(burst.index * BURST_STEP_MS, BURST_MAX_MS),
  };
  return {
    flights: [...state.flights.filter((f) => now - f.at < FLIGHT_MS), flight].slice(-MAX_FLIGHTS),
    burst,
    serial,
  };
}

function story(timeline: StoryItem[], item: StoryItem): StoryItem[] {
  return [item, ...timeline].slice(0, MAX_STORY);
}

/**
 * The state after one more item. `now` is this browser's clock (ms). With `quiet`, the
 * item is taken in without motion (no flights, pulses or arcs): used to jump ahead.
 */
export function ingest(
  state: StreamState,
  item: StreamItem,
  now: number,
  quiet = false,
): StreamState {
  if (item.event === "agent_message") {
    const message = item.data;
    if (state.messages.some((m) => m.id === message.id)) return state;
    let next: StreamState = {
      ...state,
      messages: [...state.messages, message].slice(-MAX_MESSAGES),
    };
    if (!quiet) {
      next.activity = touched(
        next.activity,
        [activityCode(message.from), activityCode(message.to)],
        message.type,
        now,
      );
      const from = nodeOf(message.from);
      const to = nodeOf(message.to);
      if (from && to && from !== to)
        next = { ...next, ...launched(next, from, to, "message", now) };
    }
    if (STORY_MESSAGES.has(message.type)) {
      next.timeline = story(next.timeline, {
        id: `st-${message.id}`,
        seenAt: now,
        kind: "message",
        message,
      });
    }
    if (message.type === "AWARD_SUMMARY" && !quiet) {
      next.lastAward = { conversation: message.conversation_id, at: now };
    }
    return next;
  }

  const data = item.data;
  if (data.kind === "reset") return { ...EMPTY_STREAM, serial: state.serial };

  const serial = { ...state.serial, event: state.serial.event + 1 };
  const event: PayPalEvent = { ...data, id: `ev-${serial.event}` };
  let next: StreamState = {
    ...state,
    serial,
    events: [event, ...state.events].slice(0, MAX_EVENTS),
  };
  if (!quiet) {
    next.activity = touched(
      next.activity,
      [event.shop, event.buyer, event.seller, event.supplier],
      event.kind,
      now,
    );
    const money = moneyFlight(event);
    if (money) {
      next.activity = touched(next.activity, ["hub"], event.kind, now);
      next = { ...next, ...launched(next, ...money, now) };
    }
    if (event.kind === "swap_completed" && event.seller && event.buyer) {
      next.arcs = [
        ...next.arcs.filter((a) => now - a.at < ARC_MS),
        { id: event.id, from: event.seller, to: event.buyer, kind: event.kind, at: now },
      ];
    }
  }
  // Ordinary charges would drown the story; only short deliveries make a line.
  const routine = event.kind === "captured" && !event.partial;
  if (STORY_EVENTS.has(event.kind) && !routine) {
    next.timeline = story(next.timeline, {
      id: `st-${event.id}`,
      seenAt: now,
      kind: "event",
      event,
    });
  }
  return next;
}
