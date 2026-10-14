/**
 * Turns the things that happen during a Swarm week into plain sentences for the narrator.
 * Pure functions: no React, no fetching.
 */

import type { Overview, Step } from "@/lib/api";
import { CATEGORY_LABEL, money, moneyWhole } from "@/lib/format";
import type { StoryItem } from "@/lib/live";

export type Tone = "neutral" | "honey" | "good" | "warning" | "critical";

export type Caption = {
  /** The headline, one sentence. */
  title: string;
  /** Optional second line with the detail. */
  detail?: string;
  tone: Tone;
  /** Which step of the week this belongs to, when known. */
  step?: string;
};

type Names = Record<string, string>;

const name = (names: Names, code: unknown): string =>
  typeof code === "string" && code ? (names[code] ?? code) : "A shop";

/** One story item as a caption, or null when it isn't worth a line of its own. */
export function describeStory(item: StoryItem, names: Names, steps: Step[]): Caption | null {
  if (item.kind === "message") {
    const { message } = item;
    const category = CATEGORY_LABEL[String(message.payload.category ?? "")]?.toLowerCase();
    switch (message.type) {
      case "RFQ":
        return {
          title: `Three supplier agents are asked to quote${category ? ` for ${category}` : ""}.`,
          detail: message.text,
          tone: "honey",
          step: "negotiation",
        };
      case "FINAL_CALL":
        return {
          title: `Last round: ${name(names, message.to.split(":")[1])} is told the price to beat.`,
          detail: message.text,
          tone: "honey",
          step: "negotiation",
        };
      case "AWARD_SUMMARY":
        return { title: message.text, tone: "good", step: "negotiation" };
      case "NO_AWARD":
        return { title: message.text, tone: "warning", step: "negotiation" };
      case "CLAIM_OPEN": {
        const amount = money(Number(message.payload.amount_cents ?? 0));
        const supplier = name(names, message.payload.supplier);
        return {
          title: message.payload.held_back
            ? `A claim is open, so ${amount} is held back from ${supplier}.`
            : `A claim is open for ${amount}.`,
          detail: message.text,
          tone: "warning",
          step: message.payload.held_back ? "settlement" : undefined,
        };
      }
      case "FLASH_DEAL":
        return {
          title: `${name(names, message.from.split(":")[1])} posts a flash deal to the shops that use it.`,
          detail: message.text,
          tone: "honey",
        };
      default:
        return null;
    }
  }

  const { event } = item;
  const amount = money(event.amount_cents ?? 0);
  switch (event.kind) {
    case "step_started": {
      const step = steps.find((s) => s.key === event.step);
      return {
        title: step?.title ?? String(event.title ?? "Next step"),
        detail: step ? `${step.description}.` : undefined,
        tone: "neutral",
        step: String(event.step ?? ""),
      };
    }
    case "captured":
      return event.partial
        ? {
            title: `${name(names, event.shop)} got a short delivery, so PayPal charges only ${amount}.`,
            detail: `${money(event.hold_cents ?? 0)} was held; the rest goes straight back.`,
            tone: "warning",
            step: "settlement",
          }
        : null;
    case "refunded":
      return {
        title: `${name(names, event.shop)} is refunded ${amount}.`,
        detail: typeof event.reason === "string" ? event.reason : undefined,
        tone: "warning",
      };
    case "supplier_paid": {
      const withheld = Number(event.withheld_cents ?? 0);
      return {
        title: `${name(names, event.supplier)} is paid ${amount} by PayPal Payouts.`,
        detail: withheld
          ? `${money(withheld)} is kept back until an open claim is settled.`
          : "After the invoice passed the check, minus Swarm's fee.",
        tone: "good",
        step: "settlement",
      };
    }
    case "invoice_checked":
      return event.approved
        ? {
            title: `Invoice ${String(event.invoice_number ?? "")} matches the deal and the delivery.`,
            detail: `${name(names, event.supplier)} billed ${amount}. Paying it now.`,
            tone: "good",
            step: "settlement",
          }
        : {
            title: `Invoice rejected: ${name(names, event.supplier)} overcharged ${money(Number(event.overcharge_cents ?? 0))}.`,
            detail: `${String(event.invoice_number ?? "The invoice")} doesn't match the agreed prices. Nobody pays until it's corrected.`,
            tone: "critical",
            step: "settlement",
          };
    case "swap_completed":
      // Recordings made before swaps said their kind get the general wording.
      if (event.swap_kind === "SURPLUS") {
        return {
          title: `${name(names, event.seller)} sells surplus to ${name(names, event.buyer)}: ${amount}, paid on the spot.`,
          detail:
            "Stock that would have expired goes down the street; PayPal charges the buyer and pays the seller.",
          tone: "honey",
          step: "surplus",
        };
      }
      if (event.swap_kind === "EMERGENCY") {
        return {
          title: `${name(names, event.seller)} helps ${name(names, event.buyer)} out: ${amount}, paid on the spot.`,
          detail:
            "The nearest neighbour with stock to spare; PayPal charges the buyer and pays the seller.",
          tone: "honey",
          step: "emergency",
        };
      }
      return {
        title: `${name(names, event.seller)} helps ${name(names, event.buyer)}: ${amount}, paid on the spot.`,
        detail: "The buyer is charged and the seller is paid out through PayPal.",
        tone: "honey",
      };
    case "flash_deal_bought":
      return {
        title: `${name(names, event.shop)}'s agent takes ${name(names, event.supplier)}'s flash deal for ${amount}.`,
        tone: "honey",
      };
    case "approval_needed":
      return {
        title: `${name(names, event.shop)} would go over its weekly limit, so its agent asks the owner first.`,
        detail: typeof event.question === "string" ? event.question : undefined,
        tone: "warning",
      };
    case "hold_failed":
      return {
        title: `${name(names, event.shop)}'s hold didn't go through.`,
        detail: typeof event.reason === "string" ? event.reason : undefined,
        tone: "critical",
        step: "holds",
      };
    case "week_summary":
      return {
        title: `Week complete: ${moneyWhole(Number(event.saved_cents ?? 0))} saved across the street.`,
        detail: event.books_balanced ? "Every cent is accounted for." : undefined,
        tone: "good",
        step: "report",
      };
    default:
      return null;
  }
}

/** What to say when nothing has just happened (page opened mid-week, or before the start). */
export function restingCaption(overview: Overview): Caption {
  const done = overview.steps.filter((s) => s.status === "done").length;
  const next = overview.steps.find((s) => s.status === "next");
  if (overview.running) {
    return {
      title: next ? next.title : "The week is running",
      detail: next ? `${next.description}.` : undefined,
      tone: "honey",
      step: next?.key,
    };
  }
  if (done === 0) {
    return {
      title: "Monday morning. Twelve shops, three suppliers, one week.",
      detail: "Run the week to watch the agents buy together and PayPal move the money.",
      tone: "neutral",
    };
  }
  if (!next) {
    return {
      title: `Week complete: ${moneyWhole(overview.stats.saved_cents)} saved across the street.`,
      detail: `${money(overview.stats.negotiation_saved_cents)} of it won by negotiating. ${
        overview.stats.books_balanced ? "Every cent is accounted for." : ""
      }`.trim(),
      tone: "good",
      step: "report",
    };
  }
  return {
    title: `Up next: ${next.title}`,
    detail: `${next.description}.`,
    tone: "neutral",
    step: next.key,
  };
}

/** The caption to show: the newest thing worth a line, else the resting one. */
export function currentCaption(
  timeline: StoryItem[],
  names: Names,
  overview: Overview,
): { caption: Caption; id: string } {
  for (const item of timeline) {
    const caption = describeStory(item, names, overview.steps);
    if (caption) return { caption, id: item.id };
  }
  const caption = restingCaption(overview);
  return { caption, id: `rest-${caption.title}` };
}
