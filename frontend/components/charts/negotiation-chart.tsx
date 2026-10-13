"use client";

/**
 * Landed price per supplier, round by round. One colour per supplier (fixed by supplier,
 * never by rank), a legend, the final value labelled at each line's end, and a crosshair
 * tooltip listing every supplier at the hovered round.
 */

import { useState } from "react";

import type { GroupOrder } from "@/lib/api";
import { money, slotColor } from "@/lib/format";
import { niceTicks } from "@/lib/ticks";
import { useWidth } from "@/lib/use-width";

const H = 190;
const PAD = { top: 16, right: 92, bottom: 26, left: 62 };

export function NegotiationChart({
  group,
  emphasis,
}: {
  group: GroupOrder;
  /** A supplier code to draw in front; the others step back (still in their own colours). */
  emphasis?: string;
}) {
  const [hoverRound, setHoverRound] = useState<number | null>(null);
  const [frame, W] = useWidth<HTMLElement>(0);
  const bySupplier = new Map<
    string,
    { name: string; points: { round: number; cents: number }[] }
  >();
  for (const quote of group.quotes) {
    const entry = bySupplier.get(quote.supplier) ?? { name: quote.supplier_name, points: [] };
    entry.points.push({ round: quote.round, cents: quote.landed_cents });
    bySupplier.set(quote.supplier, entry);
  }
  const series = [...bySupplier.entries()].sort(([a], [b]) => a.localeCompare(b));
  if (!series.length) return null;
  const rounds = Math.max(...group.quotes.map((q) => q.round));
  const values = group.quotes.map((q) => q.landed_cents);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = Math.max(500, (hi - lo) * 0.15);
  const yMin = lo - pad;
  const yMax = hi + pad;
  const x = (round: number) =>
    PAD.left + (rounds === 1 ? 0.5 : (round - 1) / (rounds - 1)) * (W - PAD.left - PAD.right);
  const y = (cents: number) =>
    PAD.top + (1 - (cents - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);
  const winner = group.supplier?.code;

  // End labels: start at each line's last point, then push apart so none overlap.
  const labelY: Record<string, number> = {};
  const ends = series
    .map(([code, s]) => {
      const last = s.points.reduce((a, b) => (b.round > a.round ? b : a));
      return { code, y: y(last.cents) };
    })
    .sort((a, b) => a.y - b.y);
  ends.forEach((end, index) => {
    const previous = index > 0 ? labelY[ends[index - 1].code] : -Infinity;
    labelY[end.code] = Math.max(end.y, previous + 13);
  });

  return (
    <figure className="w-full" ref={frame}>
      <div className="text-ink-2 mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-hidden>
        {series.map(([code, s]) => (
          <span key={code} className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full" style={{ background: slotColor(code) }} />
            {s.name}
            {code === winner ? <span className="text-muted">(won)</span> : null}
          </span>
        ))}
      </div>
      {W > 0 ? (
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          className="block overflow-visible"
          role="img"
          aria-label={`Landed price by negotiation round. ${series
            .map(([, s]) => `${s.name}: ${s.points.map((p) => money(p.cents)).join(" to ")}`)
            .join(". ")}.`}
          onPointerLeave={() => setHoverRound(null)}
        >
          {niceTicks(yMin, yMax, 3).map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--grid)"
              />
              <text
                x={PAD.left - 8}
                y={y(tick)}
                dy="0.32em"
                textAnchor="end"
                className="tabular fill-[var(--muted)] text-[10px]"
              >
                {money(tick).replace(/\.00$/, "")}
              </text>
            </g>
          ))}
          {Array.from({ length: rounds }, (_, i) => i + 1).map((round) => (
            <g key={round}>
              <text
                x={x(round)}
                y={H - 6}
                textAnchor="middle"
                className="fill-[var(--muted)] text-[10px]"
              >
                {round === rounds && rounds > 1 ? "Final" : `Round ${round}`}
              </text>
              <rect
                x={x(round) - 30}
                y={PAD.top}
                width={60}
                height={H - PAD.top - PAD.bottom}
                fill="transparent"
                onPointerEnter={() => setHoverRound(round)}
              />
            </g>
          ))}
          {hoverRound !== null ? (
            <line
              x1={x(hoverRound)}
              x2={x(hoverRound)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="var(--axis)"
            />
          ) : null}
          {[...series]
            // The emphasised supplier is drawn last, so it sits on top.
            .sort(([a], [b]) => Number(a === emphasis) - Number(b === emphasis))
            .map(([code, s]) => {
              const points = [...s.points].sort((a, b) => a.round - b.round);
              const d = points
                .map((p, i) => `${i ? "L" : "M"}${x(p.round)},${y(p.cents)}`)
                .join(" ");
              const last = points[points.length - 1];
              const quiet = emphasis !== undefined && code !== emphasis;
              return (
                <g key={code}>
                  {/* Only the marks step back; the label stays readable. */}
                  <g opacity={quiet ? 0.5 : 1}>
                    <path
                      d={d}
                      fill="none"
                      stroke={slotColor(code)}
                      strokeWidth={quiet ? 1.5 : 2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    {points.map((p) => (
                      <circle
                        key={p.round}
                        cx={x(p.round)}
                        cy={y(p.cents)}
                        r={quiet ? 3 : 4}
                        fill={slotColor(code)}
                        stroke="var(--surface)"
                        strokeWidth={2}
                      />
                    ))}
                  </g>
                  <text
                    x={x(last.round) + 10}
                    y={labelY[code]}
                    dy="0.32em"
                    className="tabular fill-[var(--ink-2)] text-[11px]"
                  >
                    {money(last.cents)}
                  </text>
                </g>
              );
            })}
        </svg>
      ) : (
        <div style={{ height: H }} aria-hidden />
      )}
      {hoverRound !== null ? (
        <div className="mt-1 flex flex-wrap gap-x-4 text-xs" role="status">
          {series.map(([code, s]) => {
            const point = s.points.find((p) => p.round === hoverRound);
            return point ? (
              <span key={code} className="inline-flex items-center gap-1.5">
                <span className="h-0.5 w-3 rounded-full" style={{ background: slotColor(code) }} />
                <span className="tabular text-ink font-semibold">{money(point.cents)}</span>
                <span className="text-ink-2">{s.name}</span>
              </span>
            ) : null;
          })}
        </div>
      ) : null}
    </figure>
  );
}
