import type { PaymentRow } from "@/lib/api";
import type { PayPalEvent } from "@/lib/live";

/** A recorded payment as a feed event, for history from before this page was opened. */
export function paymentEvent(row: PaymentRow): PayPalEvent | null {
  const failed = row.status === "FAILED";
  const base = {
    id: `pay-${row.id}`,
    at: row.at,
    shop: row.shop?.code,
    supplier: row.supplier?.code,
    amount_cents: row.amount_cents,
    paypal_id: row.paypal_id ?? undefined,
    mode: row.mode,
    reason: row.error ?? undefined,
  };
  const kind = (() => {
    switch (row.kind) {
      case "AUTHORIZATION":
        return failed ? "hold_failed" : "hold_placed";
      case "REAUTHORIZATION":
        return "hold_reauthorized";
      case "VOID":
        return "hold_voided";
      case "REFUND":
        return "refunded";
      case "CAPTURE":
        if (failed) return "capture_failed";
        return row.related_type === "flash_deal" ? "flash_deal_bought" : "captured";
      case "SWAP_PAYMENT":
        return "swap_charged";
      case "PAYOUT":
        return row.related_type === "swap" ? "swap_payout" : "supplier_paid";
      default:
        return null;
    }
  })();
  if (!kind || (row.status === "PENDING" && !failed)) return null;
  return { ...base, kind };
}
