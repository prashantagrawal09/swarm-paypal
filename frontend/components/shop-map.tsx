"use client";

/**
 * Tiong Bahru, drawn: the estate's streets, every shop as a pin coloured by where its week
 * stands, a pulse when its agent is talking, and an arc when neighbours swap stock.
 * Pin colours are status colours, so each also carries an icon in the legend and a word in
 * the tooltip; nothing relies on colour alone.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { cx } from "@/components/ui";
import type { ShopSummary } from "@/lib/api";
import { initials, money } from "@/lib/format";
import { useLive } from "@/lib/live";
import { useNow } from "@/lib/use-now";

const W = 720;
const H = 440;
const PAD = 54;
const PIN = 15;

// The estate's bounding box (a little wider than the shops) and its main streets.
const BOUNDS = { south: 1.2826, north: 1.2866, west: 103.8284, east: 103.8342 };
const STREETS: {
  name: string;
  sign?: string;
  points: [number, number][];
  major?: boolean;
}[] = [
  {
    name: "Tiong Bahru Road",
    points: [
      [1.2862, 103.8284],
      [1.2861, 103.8342],
    ],
    major: true,
  },
  {
    name: "Seng Poh Road",
    points: [
      [1.2853, 103.8288],
      [1.2849, 103.834],
    ],
  },
  {
    name: "Eng Hoon Street",
    points: [
      [1.2832, 103.8288],
      [1.2832, 103.8318],
    ],
  },
  {
    name: "Moh Guan Terrace",
    sign: "Moh Guan Tce",
    points: [
      [1.283, 103.8289],
      [1.2858, 103.8289],
    ],
  },
  {
    name: "Kim Pong Road",
    sign: "Kim Pong Rd",
    points: [
      [1.283, 103.8305],
      [1.2862, 103.8305],
    ],
  },
  {
    name: "Yong Siak Street",
    sign: "Yong Siak St",
    points: [
      [1.283, 103.8313],
      [1.2848, 103.8313],
    ],
  },
  {
    name: "Guan Chuan Street",
    sign: "Guan Chuan St",
    points: [
      [1.283, 103.8335],
      [1.285, 103.8335],
    ],
  },
];

type PinState = "idle" | "approval" | "held" | "charged" | "failed";

const PIN_STATE: Record<PinState, { label: string; fill: string; ring: string; ink: string }> = {
  idle: {
    label: "Waiting for the week",
    fill: "var(--surface)",
    ring: "var(--line-strong)",
    ink: "var(--ink-2)",
  },
  approval: {
    label: "Needs the owner",
    fill: "var(--warning-soft)",
    ring: "var(--warning)",
    ink: "var(--warning-ink)",
  },
  held: {
    label: "Money held",
    fill: "var(--honey-soft)",
    ring: "var(--honey)",
    ink: "var(--honey-ink)",
  },
  charged: {
    label: "Delivered and charged",
    fill: "var(--good-soft)",
    ring: "var(--good)",
    ink: "var(--good-ink)",
  },
  failed: {
    label: "Problem",
    fill: "var(--critical-soft)",
    ring: "var(--critical)",
    ink: "var(--critical)",
  },
};

function pinState(shop: ShopSummary): PinState {
  const statuses = shop.orders.map((o) => o.status);
  if (statuses.includes("FAILED")) return "failed";
  if (shop.pending_approvals > 0) return "approval";
  if (statuses.some((s) => s === "AUTHORIZED")) return "held";
  if (
    statuses.length &&
    statuses.every((s) => ["CAPTURED", "SETTLED", "REFUNDED", "VOIDED"].includes(s))
  ) {
    return "charged";
  }
  return "idle";
}

function project(lat: number, lng: number): [number, number] {
  const x = PAD + ((lng - BOUNDS.west) / (BOUNDS.east - BOUNDS.west)) * (W - PAD * 2);
  const y = PAD + ((BOUNDS.north - lat) / (BOUNDS.north - BOUNDS.south)) * (H - PAD * 2);
  return [x, y];
}

/** Nudges pins that would overlap (the market stalls share a building). Deterministic. */
function relax(points: { code: string; x: number; y: number }[]) {
  const out = points.map((p) => ({ ...p }));
  const min = PIN * 2 + 4;
  for (let pass = 0; pass < 40; pass++) {
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const dx = out[j].x - out[i].x;
        const dy = out[j].y - out[i].y;
        const d = Math.hypot(dx, dy) || 0.01;
        if (d < min) {
          const push = (min - d) / 2;
          const ux = dx / d;
          const uy = dy / d;
          out[i].x -= ux * push;
          out[i].y -= uy * push;
          out[j].x += ux * push;
          out[j].y += uy * push;
        }
      }
    }
  }
  return Object.fromEntries(out.map((p) => [p.code, [p.x, p.y] as [number, number]]));
}

export function ShopMap({ shops, className }: { shops: ShopSummary[]; className?: string }) {
  const router = useRouter();
  const { activity, arcs } = useLive();
  const [hover, setHover] = useState<string | null>(null);
  // Re-render while pulses and arcs are fresh so they fade on time.
  const now = useNow(500);

  const positions = useMemo(
    () =>
      relax(
        shops.map((shop) => {
          const [x, y] = project(shop.lat, shop.lng);
          return { code: shop.code, x, y };
        }),
      ),
    [shops],
  );

  const hovered = shops.find((s) => s.code === hover) ?? null;
  const used = new Set(shops.map(pinState));

  return (
    <div className={cx("relative", className)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label={`Map of Tiong Bahru with ${shops.length} shops.`}
      >
        <defs>
          <pattern
            id="map-hex"
            width="28"
            height="48.5"
            patternUnits="userSpaceOnUse"
            patternTransform="scale(0.9)"
          >
            <path
              d="M14 0 28 8.08v16.17L14 32.33 0 24.25V8.08Z M14 32.33V48.5"
              fill="none"
              stroke="var(--grid)"
              strokeWidth="1"
            />
          </pattern>
          <radialGradient id="map-fade" cx="50%" cy="50%" r="65%">
            <stop offset="60%" stopColor="var(--surface)" stopOpacity="0" />
            <stop offset="100%" stopColor="var(--surface)" stopOpacity="1" />
          </radialGradient>
        </defs>
        <rect width={W} height={H} fill="url(#map-hex)" opacity={0.7} />
        <rect width={W} height={H} fill="url(#map-fade)" />

        {/* Streets */}
        {STREETS.map((street) => {
          const pts = street.points.map(([lat, lng]) => project(lat, lng));
          const [a, b] = pts;
          const angle = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
          // East-west streets are labelled along their west end; north-south streets get a
          // short sign just below their south end, clear of the shop pins.
          const vertical = Math.abs(angle) > 45;
          const south = a[1] > b[1] ? a : b;
          const label: [number, number] = vertical
            ? [south[0], south[1] + 18]
            : [a[0] + (b[0] - a[0]) * 0.04, a[1] + (b[1] - a[1]) * 0.04 - 8];
          const rotation = vertical ? 0 : angle;
          return (
            <g key={street.name}>
              <line
                x1={a[0]}
                y1={a[1]}
                x2={b[0]}
                y2={b[1]}
                stroke="var(--line-strong)"
                strokeWidth={street.major ? 9 : 6}
                strokeLinecap="round"
              />
              <line
                x1={a[0]}
                y1={a[1]}
                x2={b[0]}
                y2={b[1]}
                stroke="var(--surface-2)"
                strokeWidth={street.major ? 6 : 3.5}
                strokeLinecap="round"
              />
              <text
                x={label[0]}
                y={label[1]}
                transform={`rotate(${rotation} ${label[0]} ${label[1]})`}
                textAnchor={vertical ? "middle" : "start"}
                className="fill-[var(--muted)] text-[10px] tracking-wide uppercase"
              >
                {vertical ? (street.sign ?? street.name) : street.name}
              </text>
            </g>
          );
        })}

        {/* Market block */}
        {(() => {
          const [mx, my] = project(1.28512, 103.83242);
          return (
            <g>
              <rect
                x={mx - 46}
                y={my - 30}
                width={92}
                height={60}
                rx={10}
                fill="var(--surface-2)"
                stroke="var(--line)"
              />
              <text
                x={mx}
                y={my - 38}
                textAnchor="middle"
                className="fill-[var(--muted)] text-[10px] tracking-wide uppercase"
              >
                Tiong Bahru Market
              </text>
            </g>
          );
        })()}

        {/* Swap arcs (seller -> buyer) */}
        {arcs
          .filter((arc) => now - arc.at < 8000)
          .map((arc) => {
            const from = positions[arc.from];
            const to = positions[arc.to];
            if (!from || !to) return null;
            const mx = (from[0] + to[0]) / 2;
            const my =
              (from[1] + to[1]) / 2 -
              Math.max(40, Math.hypot(to[0] - from[0], to[1] - from[1]) * 0.35);
            const d = `M${from[0]},${from[1]} Q${mx},${my} ${to[0]},${to[1]}`;
            return (
              <g key={arc.id} opacity={Math.max(0, 1 - (now - arc.at) / 8000)}>
                <path
                  d={d}
                  fill="none"
                  stroke="var(--honey)"
                  strokeWidth={6}
                  strokeOpacity={0.25}
                  strokeLinecap="round"
                />
                <path
                  d={d}
                  fill="none"
                  stroke="var(--honey-ink)"
                  strokeWidth={2}
                  strokeLinecap="round"
                  className="draw"
                  pathLength={1}
                  style={{ "--dash": 1 } as React.CSSProperties}
                />
              </g>
            );
          })}

        {/* Pins */}
        {shops.map((shop) => {
          const position = positions[shop.code];
          if (!position) return null;
          const [x, y] = position;
          const state = PIN_STATE[pinState(shop)];
          const recent = activity[shop.code];
          const active = recent && now - recent.at < 2600;
          const isHover = hover === shop.code;
          return (
            <g
              key={shop.code}
              transform={`translate(${x} ${y})`}
              className="cursor-pointer outline-none"
              tabIndex={0}
              role="link"
              aria-label={`${shop.name}: ${state.label}. Saved ${money(shop.saved_week_cents)} this week.`}
              onPointerEnter={() => setHover(shop.code)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(shop.code)}
              onBlur={() => setHover(null)}
              onClick={() => router.push(`/shop/${shop.code}`)}
              onKeyDown={(event) => {
                if (event.key === "Enter") router.push(`/shop/${shop.code}`);
              }}
            >
              {active ? (
                <circle
                  r={PIN}
                  fill="none"
                  stroke="var(--honey)"
                  strokeWidth={3}
                  className="ping"
                  key={recent.at}
                />
              ) : null}
              <circle r={PIN + 3} fill="var(--surface)" />
              <circle
                r={isHover ? PIN + 1.5 : PIN}
                fill={state.fill}
                stroke={state.ring}
                strokeWidth={2.5}
                style={{ transition: "r 150ms ease, fill 400ms ease, stroke 400ms ease" }}
              />
              <text
                textAnchor="middle"
                dy="0.35em"
                className="pointer-events-none text-[10px] font-semibold"
                fill={state.ink}
              >
                {initials(shop.name).toUpperCase()}
              </text>
              {shop.mode === "REAL" ? (
                <circle
                  cx={PIN - 2}
                  cy={-PIN + 2}
                  r={4.5}
                  fill="var(--real)"
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ) : null}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hovered && positions[hovered.code] ? (
        <MapTooltip shop={hovered} position={positions[hovered.code]} state={pinState(hovered)} />
      ) : null}

      {/* Legend: only the states on the map right now, each with a swatch and a word. */}
      <ul className="text-ink-2 mt-2 flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs">
        {(Object.keys(PIN_STATE) as PinState[])
          .filter((key) => used.has(key))
          .map((key) => (
            <li key={key} className="inline-flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-full border-2"
                style={{ background: PIN_STATE[key].fill, borderColor: PIN_STATE[key].ring }}
                aria-hidden
              />
              {PIN_STATE[key].label}
            </li>
          ))}
        {shops.some((s) => s.mode === "REAL") ? (
          <li className="inline-flex items-center gap-1.5">
            <span className="bg-real h-2 w-2 rounded-full" aria-hidden /> Real PayPal sandbox
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function MapTooltip({
  shop,
  position,
  state,
}: {
  shop: ShopSummary;
  position: [number, number];
  state: PinState;
}) {
  const left = `${(position[0] / W) * 100}%`;
  const top = `${(position[1] / H) * 100}%`;
  const flip = position[0] > W * 0.62;
  return (
    <div
      className="border-line bg-surface pointer-events-none absolute z-10 w-56 rounded-xl border p-3 text-xs shadow-[var(--shadow)]"
      style={{
        left,
        top,
        transform: `translate(${flip ? "calc(-100% - 22px)" : "22px"}, -50%)`,
      }}
      role="tooltip"
    >
      <div className="text-ink font-semibold">{shop.name}</div>
      <div className="text-muted">
        {shop.owner} · {shop.kind}
      </div>
      <div className="text-ink-2 mt-2 flex items-center gap-1.5">
        <span
          className="h-2 w-2 rounded-full"
          style={{ background: PIN_STATE[state].ring }}
          aria-hidden
        />
        {PIN_STATE[state].label}
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-y-1">
        <dt className="text-muted">Saved this week</dt>
        <dd className="tabular text-ink text-right font-medium">{money(shop.saved_week_cents)}</dd>
        <dt className="text-muted">Committed</dt>
        <dd className="tabular text-ink text-right">
          {money(shop.committed_cents)}
          <span className="text-muted"> / {money(shop.limit_cents).replace(/\.00$/, "")}</span>
        </dd>
      </dl>
    </div>
  );
}
