"use client";

/**
 * The price ladder: a supplier's tier prices (a step line) against quantity, with three
 * marked positions: one shop buying alone, the pooled group at its tier, and the negotiated
 * price. Single series, so no legend; the three positions are labelled directly.
 * Emphasis form: the ladder is quiet ink, the group's position is the accent.
 */

import { useId, useState } from "react";

import type { LadderEntry } from "@/lib/api";
import { money } from "@/lib/format";
import { useWidth } from "@/lib/use-width";

const H = 210;
const PAD = { top: 18, right: 18, bottom: 30, left: 52 };

export function PriceLadder({ entry, shops }: { entry: LadderEntry; shops: number }) {
  const clip = useId();
  const [hover, setHover] = useState<string | null>(null);
  const [frame, W] = useWidth<HTMLElement>(0);
  if (!entry.tiers.length || !entry.qty) return null;

  const perShop = Math.max(1, Math.round(entry.qty / Math.max(1, shops)));
  const lastTier = entry.tiers[entry.tiers.length - 1];
  const xMax = Math.max(entry.qty * 1.18, lastTier.min_qty * 1.35);
  const prices = entry.tiers.map((t) => t.unit_price_cents);
  const agreed = entry.agreed_cents ?? null;
  const yMaxRaw = Math.max(...prices);
  const yMinRaw = Math.min(...prices, agreed ?? Infinity);
  const span = Math.max(1, yMaxRaw - yMinRaw);
  const yMax = yMaxRaw + span * 0.12;
  const yMin = Math.max(0, yMinRaw - span * 0.28);

  const x = (q: number) => PAD.left + (q / xMax) * (W - PAD.left - PAD.right);
  const y = (cents: number) =>
    PAD.top + (1 - (cents - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);
  const tierAt = (q: number) =>
    entry.tiers.reduce(
      (price, tier) => (q >= tier.min_qty ? tier.unit_price_cents : price),
      prices[0],
    );

  // Step path through the tiers.
  let path = "";
  entry.tiers.forEach((tier, index) => {
    const startX = x(index === 0 ? 0 : tier.min_qty);
    const endX = x(index + 1 < entry.tiers.length ? entry.tiers[index + 1].min_qty : xMax);
    path += `${index === 0 ? "M" : "L"}${startX},${y(tier.unit_price_cents)} L${endX},${y(tier.unit_price_cents)} `;
  });

  const ticksY = niceTicks(yMin, yMax, 4);
  const alonePrice = tierAt(perShop);
  const groupPrice = entry.tier_price_cents ?? tierAt(entry.qty);
  const points = [
    {
      key: "alone",
      q: perShop,
      price: alonePrice,
      label: `1 shop alone: ${money(alonePrice)}`,
      accent: false,
    },
    {
      key: "group",
      q: entry.qty,
      price: groupPrice,
      label: `${shops} shops: ${money(groupPrice)}`,
      accent: true,
    },
    ...(agreed !== null && agreed < groupPrice
      ? [
          {
            key: "deal",
            q: entry.qty,
            price: agreed,
            label: `Negotiated: ${money(agreed)}`,
            accent: true,
          },
        ]
      : []),
  ];

  return (
    <figure className="w-full" ref={frame}>
      {W > 0 ? (
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          className="block overflow-visible"
          role="img"
          aria-label={`Price per ${entry.unit} of ${entry.name} by quantity. One shop alone pays ${money(alonePrice)}, ${shops} shops together pay ${money(groupPrice)}${agreed ? `, negotiated ${money(agreed)}` : ""}.`}
        >
          <defs>
            <clipPath id={clip}>
              <rect
                x={PAD.left}
                y={PAD.top}
                width={W - PAD.left - PAD.right}
                height={H - PAD.top - PAD.bottom}
              />
            </clipPath>
          </defs>
          {ticksY.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--grid)"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 8}
                y={y(tick)}
                dy="0.32em"
                textAnchor="end"
                className="tabular fill-[var(--muted)] text-[10px]"
              >
                {money(tick)}
              </text>
            </g>
          ))}
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={H - PAD.bottom}
            y2={H - PAD.bottom}
            stroke="var(--axis)"
            strokeWidth={1}
          />
          {thin(
            entry.tiers.map((t) => ({ key: t.min_qty, x: x(t.min_qty) })),
            30,
          ).map(({ key: minQty, x: tx }) => (
            <text
              key={minQty}
              x={tx}
              y={H - PAD.bottom + 16}
              textAnchor="middle"
              className="tabular fill-[var(--muted)] text-[10px]"
            >
              {minQty === 1 ? "1" : `${minQty}+`}
            </text>
          ))}
          <text
            x={W - PAD.right}
            y={H - 4}
            textAnchor="end"
            className="fill-[var(--muted)] text-[10px]"
          >
            quantity ({entry.units})
          </text>

          {/* The ladder (quiet) and the group's quantity (accent). */}
          <path
            d={path}
            fill="none"
            stroke="var(--ink-2)"
            strokeOpacity={0.55}
            strokeWidth={2}
            strokeLinejoin="round"
            clipPath={`url(#${clip})`}
          />
          <line
            x1={x(entry.qty)}
            x2={x(entry.qty)}
            y1={PAD.top}
            y2={H - PAD.bottom}
            stroke="var(--s1)"
            strokeOpacity={0.35}
            strokeWidth={1}
          />
          {agreed !== null && agreed < groupPrice ? (
            <line
              x1={x(entry.qty)}
              x2={x(entry.qty)}
              y1={y(groupPrice)}
              y2={y(agreed)}
              stroke="var(--s1)"
              strokeWidth={2}
            />
          ) : null}

          {points.map((point) => {
            const cx = x(point.q);
            const cy = y(point.price);
            const anchorRight = cx > W * 0.6;
            return (
              <g
                key={point.key}
                onPointerEnter={() => setHover(point.key)}
                onPointerLeave={() => setHover(null)}
                tabIndex={0}
                onFocus={() => setHover(point.key)}
                onBlur={() => setHover(null)}
                className="outline-none"
              >
                <circle cx={cx} cy={cy} r={12} fill="transparent" />
                <circle
                  cx={cx}
                  cy={cy}
                  r={hover === point.key ? 6 : 5}
                  fill={point.accent ? "var(--s1)" : "var(--surface)"}
                  stroke={point.accent ? "var(--surface)" : "var(--ink-2)"}
                  strokeWidth={2}
                />
                <text
                  x={cx + (anchorRight ? -10 : 10)}
                  y={cy + (point.key === "deal" ? 14 : -10)}
                  textAnchor={anchorRight ? "end" : "start"}
                  className={`tabular text-[11px] ${point.accent ? "fill-[var(--ink)] font-semibold" : "fill-[var(--ink-2)]"}`}
                >
                  {point.label}
                </text>
              </g>
            );
          })}
        </svg>
      ) : (
        <div style={{ height: H }} aria-hidden />
      )}
      <figcaption className="sr-only">
        Tiers: {entry.tiers.map((t) => `${t.min_qty}+ at ${money(t.unit_price_cents)}`).join(", ")}.
      </figcaption>
    </figure>
  );
}

export function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min;
  if (span <= 0) return [min];
  const raw = span / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => span / s <= count + 1) ?? raw;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(Math.round(v));
  return ticks;
}

/** Drops tick labels that would sit closer than `gap` px to the previous one. */
export function thin<T extends { x: number }>(ticks: T[], gap: number): T[] {
  const kept: T[] = [];
  for (const tick of ticks) {
    if (!kept.length || tick.x - kept[kept.length - 1].x >= gap) kept.push(tick);
  }
  return kept;
}
