"use client";

/**
 * Before -> after per category: what this order would cost buying alone (light dot) and
 * what it cost through Swarm (dark dot), joined by a line, with the saving at the end.
 * One hue, two shades; values are labelled, so colour never carries meaning alone.
 */

import { money } from "@/lib/format";
import { CATEGORY_LABEL } from "@/lib/format";

type Row = { category: string; alone_cents: number; paid_cents: number; saved_cents: number };

export function Dumbbell({ rows }: { rows: Row[] }) {
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => r.alone_cents)) * 1.04;
  const scale = (cents: number) => `${(cents / max) * 100}%`;
  return (
    <figure>
      <div className="text-ink-2 mb-3 flex gap-4 text-xs" aria-hidden>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-surface h-2.5 w-2.5 rounded-full border-2 border-[var(--s1)]" />{" "}
          Buying alone
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-[var(--s1)]" /> Through Swarm
        </span>
      </div>
      <ul className="space-y-3">
        {rows.map((row) => (
          <li
            key={row.category}
            className="grid grid-cols-[7.5rem_1fr_5.5rem] items-center gap-3 text-sm"
          >
            <span className="text-ink-2 truncate">
              {CATEGORY_LABEL[row.category] ?? row.category}
            </span>
            <div
              className="relative h-4"
              title={`${money(row.paid_cents)} instead of ${money(row.alone_cents)}`}
            >
              <div className="absolute top-1/2 h-px w-full bg-[var(--grid)]" />
              <div
                className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-[var(--s1)] opacity-50"
                style={{
                  left: scale(row.paid_cents),
                  width: `calc(${scale(row.alone_cents)} - ${scale(row.paid_cents)})`,
                }}
              />
              <span
                className="bg-surface absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--s1)]"
                style={{ left: scale(row.alone_cents) }}
              />
              <span
                className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--s1)] ring-2 ring-[var(--surface)]"
                style={{ left: scale(row.paid_cents) }}
              />
            </div>
            <span className="tabular text-good-ink text-right font-medium">
              -{money(row.saved_cents)}
            </span>
          </li>
        ))}
      </ul>
      <figcaption className="sr-only">
        {rows
          .map((r) => `${r.category}: ${money(r.paid_cents)} instead of ${money(r.alone_cents)}`)
          .join("; ")}
      </figcaption>
    </figure>
  );
}
