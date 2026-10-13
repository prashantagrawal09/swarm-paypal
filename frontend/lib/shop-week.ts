/**
 * One shop's week as a short list of things that happened, in order, and what happened to
 * its money. Pure: built from what the shop page has already loaded.
 */

import type { PaymentRow, ShopDetail, ShopOrderLine, Step, SwapRow } from "@/lib/api";
import { money } from "@/lib/format";

export type WeekEventKind =
  "proposal" | "deal" | "hold" | "flash" | "delivery" | "refund" | "swap" | "report";

export type WeekEvent = {
  key: string;
  kind: WeekEventKind;
  /** When it happened (ISO), when known. */
  at: string | null;
  title: string;
  detail?: string;
};

export type WeekMoney = {
  heldCents: number;
  chargedCents: number;
  /** The part of the holds that was never charged. */
  releasedCents: number;
  refundedCents: number;
};

export type ShopWeek = { events: WeekEvent[]; money: WeekMoney };

const capital = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

export function shopWeek({
  shop,
  orders,
  payments,
  swaps,
  steps,
  productName = (line) => line.item,
}: {
  shop: ShopDetail;
  orders: ShopOrderLine[];
  payments: PaymentRow[];
  swaps: SwapRow[];
  steps: Step[];
  /** The everyday word for a line's product ("milk"), when the page knows it. */
  productName?: (line: ShopOrderLine) => string;
}): ShopWeek {
  const week = shop.report.week;
  const lines = orders.filter((line) => line.week === week);
  const stepAt = (key: string) => {
    const step = steps.find((s) => s.key === key);
    return step && step.status === "done" ? step.at : null;
  };
  const completed = payments.filter((p) => p.status === "COMPLETED");
  const events: WeekEvent[] = [];

  // Monday: the proposal and the owner's answer.
  const proposal = shop.approvals.find((a) => a.kind === "WEEKLY_NEEDS");
  if (proposal) {
    const answer =
      proposal.status === "APPROVED"
        ? `${shop.owner} approved it`
        : proposal.status === "PENDING"
          ? `${shop.owner} hasn't answered yet`
          : proposal.status === "REJECTED"
            ? `${shop.owner} skipped this week`
            : `${shop.owner} changed it`;
    events.push({
      key: "proposal",
      kind: "proposal",
      at: proposal.at,
      title: `The agent proposed the week's order and ${answer}.`,
      detail: shop.forecast.note || undefined,
    });
  }

  // Tuesday: the deals it joined, with the product where pooling helped most.
  const priced = lines.filter((l) => l.unit_price_cents && l.alone_unit_price_cents);
  if (priced.length) {
    const categories = new Set(priced.map((l) => l.category)).size;
    const best = [...priced].sort(
      (a, b) =>
        1 -
        b.unit_price_cents! / b.alone_unit_price_cents! -
        (1 - a.unit_price_cents! / a.alone_unit_price_cents!),
    )[0];
    events.push({
      key: "deal",
      kind: "deal",
      at: stepAt("negotiation"),
      title: `Joined ${categories} group ${categories === 1 ? "order" : "orders"} with the neighbours.`,
      detail: `${capital(best.item)}: ${money(best.unit_price_cents)} per ${best.unit}, instead of ${money(best.alone_unit_price_cents)} alone.`,
    });
  }

  // The money on this week's orders (each order's totals are repeated on its lines).
  const perOrder = new Map<string, ShopOrderLine>();
  for (const line of lines) perOrder.set(line.shop_order_id, line);
  const heldCents = [...perOrder.values()].reduce((sum, l) => sum + l.hold_cents, 0);
  const chargedCents = [...perOrder.values()].reduce((sum, l) => sum + l.captured_cents, 0);
  const refundedCents = [...perOrder.values()].reduce((sum, l) => sum + l.refunded_cents, 0);
  const settled = [...perOrder.values()].filter((l) => l.captured_cents > 0);
  const releasedCents = settled.reduce((sum, l) => sum + (l.hold_cents - l.captured_cents), 0);

  const holds = completed.filter(
    (p) => p.kind === "AUTHORIZATION" && p.related_type === "shop_order",
  );
  if (heldCents > 0) {
    events.push({
      key: "hold",
      kind: "hold",
      at: holds.length ? holds[holds.length - 1].at : stepAt("holds"),
      title: `PayPal held ${money(heldCents)}.`,
      detail: `Reserved on the owner's PayPal, not taken. The weekly limit is ${money(shop.limit_cents)}.`,
    });
  }

  for (const payment of completed) {
    if (payment.kind === "CAPTURE" && payment.related_type === "flash_deal") {
      events.push({
        key: `flash-${payment.id}`,
        kind: "flash",
        at: payment.at,
        title: `The agent took a supplier's flash deal for ${money(payment.amount_cents)}.`,
        detail: "Inside the rules the owner set, so nobody had to be asked.",
      });
    }
  }

  // Thursday: what arrived, and what that did to the charge.
  if (chargedCents > 0) {
    const captures = completed.filter(
      (p) => p.kind === "CAPTURE" && p.related_type === "shop_order",
    );
    const short = lines.find(
      (l) => l.qty_delivered !== null && l.qty_delivered < l.qty_requested && l.captured_cents > 0,
    );
    events.push({
      key: "delivery",
      kind: "delivery",
      at: captures.length ? captures[0].at : stepAt("settlement"),
      title: short
        ? `${short.qty_delivered} of ${short.qty_requested} ${short.unit} ${productName(short)} arrived, so PayPal charged ${money(chargedCents)} and released ${money(releasedCents)}.`
        : `Everything arrived. PayPal charged ${money(chargedCents)}.`,
      detail: short
        ? "Charged for what came. The rest of the hold went back without anyone asking."
        : releasedCents > 0
          ? `${money(releasedCents)} of the holds was not needed and went back.`
          : undefined,
    });
  }

  for (const payment of completed) {
    if (payment.kind === "REFUND") {
      events.push({
        key: `refund-${payment.id}`,
        kind: "refund",
        at: payment.at,
        title: `${money(payment.amount_cents)} refunded for a claim.`,
        detail: "Back to the PayPal payment it came from.",
      });
    }
  }

  for (const swap of swaps) {
    if (swap.status !== "COMPLETED" || !swap.role) continue;
    const what = `${swap.qty} ${swap.unit} ${swap.product_name}`;
    const selling = swap.role === "seller";
    const other = (selling ? swap.buyer : swap.seller)?.name ?? "a neighbour";
    const title =
      swap.kind === "SURPLUS"
        ? selling
          ? `Sold ${what} to ${other} before it expired: +${money(swap.price_cents)}.`
          : `Bought ${what} from ${other}${swap.discount_pct ? ` at ${swap.discount_pct}% off` : ""}: ${money(swap.price_cents)}.`
        : selling
          ? `Helped ${other} out with ${what}: +${money(swap.price_cents)}.`
          : `Ran out of ${swap.product_name}; ${other} lent ${what}: ${money(swap.price_cents)}.`;
    events.push({
      key: `swap-${swap.id}`,
      kind: "swap",
      at: swap.at,
      title,
      detail: selling ? "Paid straight to the owner's PayPal." : "Paid on the spot through PayPal.",
    });
  }

  if (stepAt("report") && shop.report.total_saved_cents > 0) {
    events.push({
      key: "report",
      kind: "report",
      at: stepAt("report"),
      title: `The week's report: ${money(shop.report.total_saved_cents)} saved.`,
      detail: `${money(shop.report.group_saved_cents)} of it from buying together.`,
    });
  }

  // In time order. Something without a time stays where the week's usual order put it,
  // straight after whatever came before.
  let previous = "";
  const timed = events.map((event) => {
    previous = event.at ?? previous;
    return { event, when: previous };
  });
  timed.sort((a, b) => a.when.localeCompare(b.when));
  return {
    events: timed.map((entry) => entry.event),
    money: { heldCents, chargedCents, releasedCents, refundedCents },
  };
}
