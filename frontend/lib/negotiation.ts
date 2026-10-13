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

export type Outcome = {
  /** How the negotiation ended for this supplier. */
  result: "won" | "lost" | "open";
  opening: number;
  final: number;
  /** For a loser, how far above the winning quote its final quote was (cents). */
  behindCents: number | null;
};

/** One supplier's showing in a group order, or null if it never quoted there. */
export function outcomeFor(group: GroupOrder, supplier: string): Outcome | null {
  const mine = group.quotes
    .filter((quote) => quote.supplier === supplier)
    .sort((a, b) => a.round - b.round);
  if (!mine.length) return null;
  const opening = mine[0].landed_cents;
  const final = mine[mine.length - 1].landed_cents;
  const winner = group.supplier?.code;
  if (!winner) return { result: "open", opening, final, behindCents: null };
  if (winner === supplier) return { result: "won", opening, final, behindCents: null };
  const winning = group.quotes
    .filter((quote) => quote.supplier === winner)
    .sort((a, b) => b.round - a.round)[0];
  return {
    result: "lost",
    opening,
    final,
    behindCents: winning ? final - winning.landed_cents : null,
  };
}
