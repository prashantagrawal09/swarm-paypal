/**
 * The week as far as a stream of events has got: which steps are done, where each shop's
 * orders stand, how much money is held, charged and paid out, and the negotiation so far.
 *
 * The live pages ask the server for these. A replay can't (the server only knows how the
 * week ended), so it works them out from the events themselves. At the end of every step
 * the server's own totals arrive with the event and replace the running ones, so a replay
 * can never drift from the books.
 */

import type { ShopSummary, Stats, SupplierSummary } from "@/lib/api";
import type { StreamItem } from "@/lib/stream-state";

export type StepProgress = "pending" | "running" | "done";

export type QuoteTrail = {
  supplier: string;
  /** Landed totals (items plus delivery), one per round, in cents. */
  landed: number[];
  declined: boolean;
};

export type Negotiation = {
  conversation: string;
  category: string;
  trails: QuoteTrail[];
  round: number;
  winner: string | null;
};

export type World = {
  /** Step key -> progress. Steps not seen yet are absent (pending). */
  steps: Record<string, StepProgress>;
  /** The step that is running or was last finished. */
  step: string | null;
  stepTitle: string | null;
  /** The Swarm Clock time of the latest event (ISO). */
  at: string | null;
  /** Shop code -> order key -> { category, status }. */
  orders: Record<string, Record<string, { category: string; status: string }>>;
  /** Shops waiting for their owner. */
  approvals: Record<string, number>;
  heldCents: number;
  chargedCents: number;
  releasedCents: number;
  paidOutCents: number;
  /** Supplier code -> what PayPal has paid it so far. */
  paidTo: Record<string, number>;
  refundedCents: number;
  /** Money-moving PayPal calls so far. */
  paypalCalls: number;
  /** How many of those went to the real PayPal sandbox (the rest were simulated). */
  realCalls: number;
  /** The server's totals as of the last finished step (null before the first). */
  stats: Stats | null;
  negotiations: Negotiation[];
  /** The conversation being negotiated right now, or just decided. */
  activeNegotiation: string | null;
  invoicesRejected: number;
  finished: boolean;
};

export const EMPTY_WORLD: World = {
  steps: {},
  step: null,
  stepTitle: null,
  at: null,
  orders: {},
  approvals: {},
  heldCents: 0,
  chargedCents: 0,
  releasedCents: 0,
  paidOutCents: 0,
  paidTo: {},
  refundedCents: 0,
  paypalCalls: 0,
  realCalls: 0,
  stats: null,
  negotiations: [],
  activeNegotiation: null,
  invoicesRejected: 0,
  finished: false,
};

const cents = (value: unknown): number => (typeof value === "number" ? value : 0);

function paid(world: World, supplier: string | undefined, amount: number): World["paidTo"] {
  if (!supplier) return world.paidTo;
  return { ...world.paidTo, [supplier]: (world.paidTo[supplier] ?? 0) + amount };
}
const text = (value: unknown): string | undefined =>
  typeof value === "string" && value ? value : undefined;

function withOrder(
  world: World,
  shop: string | undefined,
  key: string | undefined,
  status: string,
  category?: string,
): World["orders"] {
  if (!shop || !key) return world.orders;
  const mine = world.orders[shop] ?? {};
  return {
    ...world.orders,
    [shop]: { ...mine, [key]: { category: category ?? mine[key]?.category ?? "", status } },
  };
}

/** "negotiation:2026-10-12:dairy" -> "DAIRY" (the category ends a negotiation's ID). */
function categoryOf(conversation: string): string {
  return (conversation.split(":").pop() ?? "").toUpperCase();
}

function negotiated(world: World, item: Extract<StreamItem, { event: "agent_message" }>): World {
  const message = item.data;
  const [fromKind, fromCode] = message.from.split(":");
  const [toKind, toCode] = message.to.split(":");
  const conversation = message.conversation_id;
  if (!conversation.startsWith("negotiation:")) return world;
  const index = world.negotiations.findIndex((n) => n.conversation === conversation);
  const current: Negotiation =
    index >= 0
      ? world.negotiations[index]
      : { conversation, category: categoryOf(conversation), trails: [], round: 0, winner: null };

  let next: Negotiation | null = null;
  if ((message.type === "QUOTE" || message.type === "FINAL_QUOTE") && fromKind === "supplier") {
    const landed = cents(message.payload?.landed_total_cents);
    if (landed > 0) {
      const trail = current.trails.find((t) => t.supplier === fromCode);
      const trails = trail
        ? current.trails.map((t) =>
            t.supplier === fromCode ? { ...t, landed: [...t.landed, landed] } : t,
          )
        : [...current.trails, { supplier: fromCode, landed: [landed], declined: false }];
      const round = Math.max(current.round, cents(message.payload?.round) || 1);
      next = { ...current, trails, round };
    }
  } else if (message.type === "DECLINE" && fromKind === "supplier") {
    const known = current.trails.some((t) => t.supplier === fromCode);
    next = {
      ...current,
      trails: known
        ? current.trails.map((t) => (t.supplier === fromCode ? { ...t, declined: true } : t))
        : [...current.trails, { supplier: fromCode, landed: [], declined: true }],
    };
  } else if (message.type === "AWARD" && toKind === "supplier") {
    next = { ...current, winner: toCode };
  } else if (message.type === "RFQ") {
    next = current;
  }
  if (!next) return world;

  const updated = next;
  const negotiations =
    index >= 0
      ? world.negotiations.map((n, i) => (i === index ? updated : n))
      : [...world.negotiations, updated];
  return { ...world, negotiations, activeNegotiation: conversation };
}

/**
 * How many money-moving PayPal calls stand behind one event. A neighbour sale charges the
 * buyer and pays the seller; a flash deal charges the shop and pays the supplier.
 */
const CALLS: Record<string, number> = {
  hold_placed: 1,
  hold_reauthorized: 1,
  hold_voided: 1,
  captured: 1,
  refunded: 1,
  supplier_paid: 1,
  swap_completed: 2,
  flash_deal_bought: 2,
};

const callsIn = (stats: Stats): number =>
  (stats.paypal_calls.REAL ?? 0) + (stats.paypal_calls.SIMULATED ?? 0);

/** The world after one more item. Pure. */
export function advance(world: World, item: StreamItem): World {
  if (item.event === "agent_message") {
    const at = item.data.at ?? world.at;
    return negotiated({ ...world, at }, item);
  }

  const event = item.data;
  const base: World = {
    ...world,
    at: text(event.at) ?? world.at,
    paypalCalls: world.paypalCalls + (CALLS[event.kind] ?? 0),
    realCalls: world.realCalls + (event.mode === "REAL" ? (CALLS[event.kind] ?? 0) : 0),
  };
  const shop = text(event.shop);
  const order = text(event.shop_order_id) ?? text(event.swap_id);
  const amount = cents(event.amount_cents);

  switch (event.kind) {
    case "reset":
      return EMPTY_WORLD;
    case "step_started":
      return {
        ...base,
        step: text(event.step) ?? base.step,
        stepTitle: text(event.title) ?? base.stepTitle,
        steps: event.step ? { ...base.steps, [String(event.step)]: "running" } : base.steps,
      };
    case "step_finished": {
      const stats = (event.stats as Stats | undefined) ?? base.stats;
      return {
        ...base,
        steps: event.step ? { ...base.steps, [String(event.step)]: "done" } : base.steps,
        stats,
        // The server's totals replace the running ones, so a replay cannot drift.
        heldCents: stats ? stats.holds_outstanding_cents : base.heldCents,
        chargedCents: stats ? stats.captured_cents : base.chargedCents,
        paidOutCents: stats ? stats.payouts_cents : base.paidOutCents,
        refundedCents: stats ? stats.refunds_cents : base.refundedCents,
        paypalCalls: stats ? callsIn(stats) : base.paypalCalls,
        realCalls: stats ? (stats.paypal_calls.REAL ?? 0) : base.realCalls,
        activeNegotiation: event.step === "negotiation" ? null : base.activeNegotiation,
      };
    }
    case "approval_needed":
      return shop
        ? { ...base, approvals: { ...base.approvals, [shop]: (base.approvals[shop] ?? 0) + 1 } }
        : base;
    case "hold_placed":
    case "hold_reauthorized":
      return {
        ...base,
        heldCents: event.kind === "hold_placed" ? base.heldCents + amount : base.heldCents,
        orders: withOrder(base, shop, order, "AUTHORIZED", text(event.category)),
        approvals: shop ? { ...base.approvals, [shop]: 0 } : base.approvals,
      };
    case "hold_failed":
      return { ...base, orders: withOrder(base, shop, order, "FAILED", text(event.category)) };
    case "hold_voided":
      return {
        ...base,
        heldCents: Math.max(0, base.heldCents - amount),
        releasedCents: base.releasedCents + amount,
        orders: withOrder(base, shop, order, "VOIDED", text(event.category)),
      };
    case "captured": {
      const hold = cents(event.hold_cents) || amount;
      return {
        ...base,
        heldCents: Math.max(0, base.heldCents - hold),
        chargedCents: base.chargedCents + amount,
        releasedCents: base.releasedCents + Math.max(0, hold - amount),
        orders: withOrder(base, shop, order, "CAPTURED", text(event.category)),
      };
    }
    case "swap_completed":
      // The buyer's hold becomes a charge, and the money goes straight to the neighbour.
      return {
        ...base,
        heldCents: Math.max(0, base.heldCents - amount),
        chargedCents: base.chargedCents + amount,
        paidOutCents: base.paidOutCents + amount,
        orders: withOrder(base, text(event.buyer), order, "CAPTURED", "SWAP"),
      };
    case "flash_deal_bought": {
      // Charged to the shop and paid on to the supplier (less the fee) in one go.
      const net = cents(event.payout_cents) || amount;
      return {
        ...base,
        chargedCents: base.chargedCents + amount,
        paidOutCents: base.paidOutCents + net,
        paidTo: paid(base, text(event.supplier), net),
      };
    }
    case "refunded":
      return { ...base, refundedCents: base.refundedCents + amount };
    case "supplier_paid":
      return {
        ...base,
        paidOutCents: base.paidOutCents + amount,
        paidTo: paid(base, text(event.supplier), amount),
      };
    case "invoice_checked":
      return event.approved === false
        ? { ...base, invoicesRejected: base.invoicesRejected + 1 }
        : base;
    case "week_summary":
      // The summary carries the same totals as a finished step.
      return { ...base, stats: event as unknown as Stats, finished: true };
    default:
      return base;
  }
}

/** The shops as the map should draw them at this point in the week. */
export function shopsAt(shops: ShopSummary[], world: World): ShopSummary[] {
  return shops.map((shop) => ({
    ...shop,
    orders: Object.values(world.orders[shop.code] ?? {}),
    pending_approvals: world.approvals[shop.code] ?? 0,
  }));
}

/** The suppliers as the map should draw them at this point in the week. */
export function suppliersAt(suppliers: SupplierSummary[], world: World): SupplierSummary[] {
  return suppliers.map((supplier) => ({
    ...supplier,
    paid_out_cents: world.paidTo[supplier.code] ?? 0,
    awards: world.negotiations.filter((n) => n.winner === supplier.code).length,
  }));
}
