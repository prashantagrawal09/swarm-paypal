/** Reading a negotiation: each supplier's opening and latest quote. Pure. */

import type { GroupOrder } from "@/lib/api";

export type Lane = {
  code: string;
  name: string;
  opening: number;
  latest: number;
  round: number;
};

/** Each supplier's opening and latest landed quote. */
export function lanes(group: GroupOrder): Lane[] {
  const bySupplier = new Map<string, Lane>();
  for (const quote of [...group.quotes].sort((a, b) => a.round - b.round)) {
    const lane = bySupplier.get(quote.supplier);
    if (!lane) {
      bySupplier.set(quote.supplier, {
        code: quote.supplier,
        name: quote.supplier_name,
        opening: quote.landed_cents,
        latest: quote.landed_cents,
        round: quote.round,
      });
    } else {
      lane.latest = quote.landed_cents;
      lane.round = quote.round;
    }
  }
  return [...bySupplier.values()].sort((a, b) => a.code.localeCompare(b.code));
}
