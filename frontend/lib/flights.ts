/**
 * Which map nodes an agent message or a payment travels between. Pure helpers, shared by the
 * live layer and the tests.
 */

import type { FlightKind, PayPalEvent } from "@/lib/stream-state";

/** Agent id -> map node token (owners sit inside their shop, so they have no node). */
export function nodeOf(agent: string): string | null {
  const [kind, code = ""] = agent.split(":");
  if (kind === "shop") return `shop:${code}`;
  if (kind === "supplier") return `supplier:${code}`;
  if (kind === "shops") return "shop:*";
  if (kind === "suppliers") return "supplier:*";
  if (kind === "coordinator" || kind === "claims") return "hub";
  return null;
}

/** The money movements worth drawing, as [from, to, kind]. */
export function moneyFlight(event: PayPalEvent): [string, string, FlightKind] | null {
  switch (event.kind) {
    case "hold_placed":
    case "hold_reauthorized":
      return event.shop ? [`shop:${event.shop}`, "hub", "hold"] : null;
    case "captured":
      return event.shop ? [`shop:${event.shop}`, "hub", "charge"] : null;
    case "hold_voided":
    case "refunded":
      return event.shop ? ["hub", `shop:${event.shop}`, "refund"] : null;
    case "supplier_paid":
      return event.supplier ? ["hub", `supplier:${event.supplier}`, "payout"] : null;
    case "flash_deal_bought":
      return event.shop && event.supplier
        ? [`shop:${event.shop}`, `supplier:${event.supplier}`, "charge"]
        : null;
    case "swap_completed":
      return event.buyer && event.seller
        ? [`shop:${event.buyer}`, `shop:${event.seller}`, "charge"]
        : null;
    default:
      return null;
  }
}
