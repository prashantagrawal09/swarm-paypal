/**
 * Playing a recorded week back: how long to wait after each item, where each day starts,
 * and the frame (stream state plus world) at any position. Pure; the hook that drives it
 * with a timer is in use-player.ts.
 */

import { EMPTY_STREAM, ingest, type StreamItem, type StreamState } from "@/lib/stream-state";
import { advance, EMPTY_WORLD, type World } from "@/lib/world-state";

export type Frame = {
  /** How many items have been played. */
  cursor: number;
  stream: StreamState;
  world: World;
};

export const EMPTY_FRAME: Frame = { cursor: 0, stream: EMPTY_STREAM, world: EMPTY_WORLD };

export const SPEEDS = [1, 2, 4] as const;
export type Speed = (typeof SPEEDS)[number];

const MONEY_KINDS = new Set([
  "hold_placed",
  "hold_voided",
  "hold_reauthorized",
  "captured",
  "refunded",
  "supplier_paid",
  "swap_completed",
  "flash_deal_bought",
]);

/**
 * Milliseconds to wait after `item` at normal speed. Agents talking to each other get
 * time to be read; an owner's taps and their agent's replies go by quickly, as they do
 * live; a new day pauses for its title.
 */
export function gapAfter(item: StreamItem): number {
  if (item.event === "agent_message") {
    const ownerSide = item.data.from.startsWith("owner:") || item.data.to.startsWith("owner:");
    // A claim that holds money back is a beat of its own: leave time to read the caption.
    if (item.data.type === "CLAIM_OPEN") return 1700;
    return ownerSide ? 28 : 380;
  }
  const kind = item.data.kind;
  if (kind === "step_started") return 1900;
  if (kind === "step_finished") return 650;
  if (kind === "week_summary") return 900;
  if (kind === "invoice_checked" || kind === "approval_needed") return 900;
  return MONEY_KINDS.has(kind) ? 70 : 40;
}

/** How long the whole recording takes at normal speed (ms). */
export function duration(items: StreamItem[]): number {
  return items.reduce((total, item) => total + gapAfter(item), 0);
}

export type Chapter = { step: string; title: string; index: number };

/** Where each step of the week starts in the recording. */
export function chapters(items: StreamItem[]): Chapter[] {
  const found: Chapter[] = [];
  items.forEach((item, index) => {
    if (item.event === "paypal" && item.data.kind === "step_started" && item.data.step) {
      found.push({ step: item.data.step, title: String(item.data.title ?? ""), index });
    }
  });
  return found;
}

/** True once the recording contains the end of the week. */
export function isComplete(items: StreamItem[]): boolean {
  return items.some((item) => item.event === "paypal" && item.data.kind === "week_summary");
}

/** Play one more item, with motion. */
export function step(frame: Frame, items: StreamItem[], now: number): Frame {
  const item = items[frame.cursor];
  if (!item) return frame;
  return {
    cursor: frame.cursor + 1,
    stream: ingest(frame.stream, item, now),
    world: advance(frame.world, item),
  };
}

/**
 * The frame at `target`, reached without motion: from `frame` when that is behind the
 * target, otherwise from the start. Used to jump to a day and to catch up with a live week.
 */
export function seek(frame: Frame, items: StreamItem[], target: number, now: number): Frame {
  const end = Math.max(0, Math.min(target, items.length));
  let { cursor, stream, world } = end >= frame.cursor ? frame : EMPTY_FRAME;
  while (cursor < end) {
    const item = items[cursor];
    stream = ingest(stream, item, now, true);
    world = advance(world, item);
    cursor += 1;
  }
  // Whatever was in the air belongs to the moment we left.
  return { cursor, stream: { ...stream, flights: [], arcs: [], activity: {} }, world };
}
