"use client";

/**
 * The swarm, drawn: Tiong Bahru's streets with every shop as a pin, the three suppliers'
 * depots along the top, and the coordinator (which also holds the money, through PayPal)
 * in the middle. Every agent message and every payment flies between the two agents
 * involved, so you can watch the week happen.
 *
 * Pin colours are status colours, and flight colours match them; each also has a word in
 * the legend and the tooltip, so nothing relies on colour alone.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { cx } from "@/components/ui";
import type { ShopSummary, SupplierSummary } from "@/lib/api";
import { initials, money, moneyWhole, slotColor } from "@/lib/format";
import { type Flight, type FlightKind, useLive } from "@/lib/live";
import { BAND, curve, H, PIN, project, relax, W } from "@/lib/map-geometry";
import { useNow } from "@/lib/use-now";

const HUB: [number, number] = [318, 289];
const HUB_R = 21;
const DEPOT = { w: 164, h: 40, y: 30 };

// The estate's main streets.
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

/** What flies, how it looks, and the word for it. */
const FLIGHT: Record<FlightKind, { label: string; stroke: string; width: number; glow: boolean }> =
  {
    message: { label: "Agent message", stroke: "var(--ink-2)", width: 1.75, glow: false },
    hold: { label: "Money held", stroke: "var(--honey)", width: 3.5, glow: true },
    charge: { label: "Charged", stroke: "var(--good)", width: 3.5, glow: true },
    payout: { label: "Paid out", stroke: "var(--ink)", width: 3.5, glow: true },
    refund: { label: "Released or refunded", stroke: "var(--warning)", width: 3.5, glow: true },
  };

export function pinState(shop: ShopSummary): PinState {
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

export function SwarmMap({
  shops,
  suppliers = [],
  heldCents = 0,
  className,
  interactive = true,
}: {
  shops: ShopSummary[];
  suppliers?: SupplierSummary[];
  /** Money currently held (authorized, not charged), shown under the coordinator. */
  heldCents?: number;
  className?: string;
  /** Off for decorative use: no tooltips, links or legend. */
  interactive?: boolean;
}) {
  const router = useRouter();
  const { activity, arcs, flights } = useLive();
  const [hover, setHover] = useState<string | null>(null);
  // Re-render while pulses, arcs and flights are fresh so they leave on time.
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

  const depots = useMemo(() => {
    const ordered = [...suppliers].sort((a, b) => a.code.localeCompare(b.code));
    const slot = W / Math.max(1, ordered.length);
    return Object.fromEntries(
      ordered.map((supplier, index) => [
        supplier.code,
        [slot * (index + 0.5), DEPOT.y + DEPOT.h / 2] as [number, number],
      ]),
    );
  }, [suppliers]);

  /** Where a node token sits; broadcasts expand to every node of that kind. */
  const resolve = (token: string): [number, number][] => {
    if (token === "hub") return [HUB];
    const [kind, code] = token.split(":");
    if (kind === "shop") {
      return code === "*" ? Object.values(positions) : positions[code] ? [positions[code]] : [];
    }
    if (kind === "supplier") {
      const docks = (p: [number, number]): [number, number] => [p[0], p[1] + DEPOT.h / 2];
      if (code === "*") return Object.values(depots).map(docks);
      return depots[code] ? [docks(depots[code])] : [];
    }
    return [];
  };

  const hovered = shops.find((s) => s.code === hover) ?? null;
  const used = new Set(shops.map(pinState));
  const hubActive = activity.hub && now - activity.hub.at < 2600;
  const flying = flights.filter((f) => now - f.at < 2600);
  const flightKinds = [...new Set(flying.map((f) => f.kind))];

  return (
    <div className={cx("relative", className)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label={`Map of Tiong Bahru: ${shops.length} shops, ${suppliers.length} suppliers and the Swarm coordinator, with messages and payments moving between them.`}
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
          <radialGradient id="map-fade" cx="50%" cy="55%" r="65%">
            <stop offset="60%" stopColor="var(--surface)" stopOpacity="0" />
            <stop offset="100%" stopColor="var(--surface)" stopOpacity="1" />
          </radialGradient>
          <filter id="flight-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" />
          </filter>
        </defs>
        <rect y={BAND} width={W} height={H - BAND} fill="url(#map-hex)" opacity={0.7} />
        <rect y={BAND} width={W} height={H - BAND} fill="url(#map-fade)" />

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

        {/* The network at rest: faint spokes from the coordinator to everyone. */}
        <g aria-hidden>
          {Object.values(positions).map((position, index) => (
            <line
              key={index}
              x1={HUB[0]}
              y1={HUB[1]}
              x2={position[0]}
              y2={position[1]}
              stroke="var(--honey)"
              strokeOpacity={0.16}
              strokeWidth={1}
            />
          ))}
          {Object.values(depots).map((position, index) => (
            <path
              key={index}
              d={curve(HUB, [position[0], position[1] + DEPOT.h / 2], 0.06)}
              fill="none"
              stroke="var(--honey)"
              strokeOpacity={0.3}
              strokeWidth={1}
              strokeDasharray="3 5"
            />
          ))}
        </g>

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

        {/* Flights: messages (thin) and money (thick, glowing) between agents. */}
        <g aria-hidden>
          {flying.flatMap((flight: Flight) => {
            const style = FLIGHT[flight.kind];
            const starts = resolve(flight.from);
            const ends = resolve(flight.to);
            return starts.flatMap((from, i) =>
              ends.map((to, j) => {
                const d = curve(from, to, flight.kind === "message" ? 0.14 : 0.08);
                const css = {
                  "--delay": `${flight.delay + (i + j) * 35}ms`,
                  "--dur": flight.kind === "message" ? "850ms" : "1150ms",
                  "--len": flight.kind === "message" ? 0.2 : 0.28,
                } as React.CSSProperties;
                return (
                  <g key={`${flight.id}-${i}-${j}`}>
                    {style.glow ? (
                      <path
                        d={d}
                        pathLength={1}
                        fill="none"
                        stroke={style.stroke}
                        strokeWidth={style.width + 5}
                        strokeLinecap="round"
                        strokeOpacity={0.55}
                        filter="url(#flight-glow)"
                        className="fly"
                        style={css}
                      />
                    ) : null}
                    <path
                      d={d}
                      pathLength={1}
                      fill="none"
                      stroke={style.stroke}
                      strokeWidth={style.width}
                      strokeLinecap="round"
                      className="fly"
                      style={css}
                    />
                  </g>
                );
              }),
            );
          })}
        </g>

        {/* Supplier depots */}
        {suppliers.map((supplier) => {
          const position = depots[supplier.code];
          if (!position) return null;
          const recent = activity[supplier.code];
          const active = recent && now - recent.at < 2600;
          const open = () => router.push(`/supplier/${supplier.code}`);
          return (
            <g
              key={supplier.code}
              transform={`translate(${position[0] - DEPOT.w / 2} ${DEPOT.y})`}
              className={interactive ? "cursor-pointer outline-none" : undefined}
              tabIndex={interactive ? 0 : undefined}
              role={interactive ? "link" : undefined}
              aria-label={`${supplier.name}, supplier. ${supplier.tagline}`}
              onClick={interactive ? open : undefined}
              onKeyDown={(event) => {
                if (interactive && event.key === "Enter") open();
              }}
            >
              {active ? (
                <rect
                  width={DEPOT.w}
                  height={DEPOT.h}
                  rx={12}
                  fill="none"
                  stroke={slotColor(supplier.code)}
                  strokeWidth={3}
                  className="ping-soft"
                  key={recent.at}
                />
              ) : null}
              <rect
                width={DEPOT.w}
                height={DEPOT.h}
                rx={12}
                fill="var(--surface)"
                stroke="var(--line-strong)"
              />
              <circle cx={18} cy={DEPOT.h / 2} r={6} fill={slotColor(supplier.code)} />
              <text x={32} y={17} className="fill-[var(--ink)] text-[11px] font-semibold">
                {supplier.name}
              </text>
              <text x={32} y={31} className="tabular fill-[var(--muted)] text-[9.5px]">
                {supplier.paid_out_cents
                  ? `paid ${moneyWhole(supplier.paid_out_cents)} by PayPal`
                  : "supplier agent"}
              </text>
              {supplier.mode === "REAL" ? (
                <circle
                  cx={DEPOT.w - 6}
                  cy={6}
                  r={4.5}
                  fill="var(--real)"
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ) : null}
            </g>
          );
        })}

        {/* The coordinator, which also holds the money through PayPal */}
        <g transform={`translate(${HUB[0]} ${HUB[1]})`} aria-label="Swarm coordinator">
          {hubActive ? (
            <circle
              r={HUB_R}
              fill="none"
              stroke="var(--honey)"
              strokeWidth={3}
              className="ping"
              key={activity.hub.at}
            />
          ) : null}
          <circle r={HUB_R + 5} fill="var(--surface)" />
          <path
            d="M0 -21 18.2 -10.5v21L0 21l-18.2 -10.5v-21Z"
            fill="var(--honey)"
            stroke="var(--surface)"
            strokeWidth={2}
          />
          <path
            d="M0 -9.5 8.2 -4.75v9.5L0 9.5l-8.2 -4.75v-9.5Z"
            fill="none"
            stroke="#1c1400"
            strokeWidth={2}
            strokeLinejoin="round"
          />
          <circle r={2.2} fill="#1c1400" />
          <text
            y={HUB_R + 17}
            textAnchor="middle"
            className="fill-[var(--ink)] text-[10px] font-semibold"
            stroke="var(--surface)"
            strokeWidth={3}
            paintOrder="stroke"
          >
            Coordinator
          </text>
          {heldCents > 0 ? (
            <text
              y={HUB_R + 29}
              textAnchor="middle"
              className="tabular fill-[var(--ink-2)] text-[9.5px]"
              stroke="var(--surface)"
              strokeWidth={3}
              paintOrder="stroke"
            >
              holding {moneyWhole(heldCents)}
            </text>
          ) : null}
        </g>

        {/* Shop pins */}
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
              className={interactive ? "cursor-pointer outline-none" : undefined}
              tabIndex={interactive ? 0 : undefined}
              role={interactive ? "link" : undefined}
              aria-label={`${shop.name}: ${state.label}. Saved ${money(shop.saved_week_cents)} this week.`}
              onPointerEnter={interactive ? () => setHover(shop.code) : undefined}
              onPointerLeave={interactive ? () => setHover(null) : undefined}
              onFocus={interactive ? () => setHover(shop.code) : undefined}
              onBlur={interactive ? () => setHover(null) : undefined}
              onClick={interactive ? () => router.push(`/shop/${shop.code}`) : undefined}
              onKeyDown={(event) => {
                if (interactive && event.key === "Enter") router.push(`/shop/${shop.code}`);
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
      {interactive && hovered && positions[hovered.code] ? (
        <MapTooltip shop={hovered} position={positions[hovered.code]} state={pinState(hovered)} />
      ) : null}

      {/* Legend: the pin states on the map now, and whatever is flying. */}
      {interactive ? (
        <ul className="text-ink-2 mt-2 flex min-h-5 flex-wrap gap-x-4 gap-y-1 px-1 text-xs">
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
          {(Object.keys(FLIGHT) as FlightKind[])
            .filter((kind) => flightKinds.includes(kind))
            .map((kind) => (
              <li key={kind} className="inline-flex items-center gap-1.5">
                <span
                  className="w-4 rounded-full"
                  style={{ background: FLIGHT[kind].stroke, height: FLIGHT[kind].width }}
                  aria-hidden
                />
                {FLIGHT[kind].label}
              </li>
            ))}
          {shops.some((s) => s.mode === "REAL") || suppliers.some((s) => s.mode === "REAL") ? (
            <li className="inline-flex items-center gap-1.5">
              <span className="bg-real h-2 w-2 rounded-full" aria-hidden /> Real PayPal sandbox
            </li>
          ) : null}
        </ul>
      ) : null}
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
