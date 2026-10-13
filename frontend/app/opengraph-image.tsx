import { ImageResponse } from "next/og";

/** The picture shown when a link to Swarm is shared. Drawn at build time; no data needed. */

export const alt =
  "Swarm: small shops buy alone and pay retail. Swarm lets them buy like a chain, with PayPal.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const HONEY = "#f2a900";
const INK = "#ffffff";
const SOFT = "#c3c2b7";

// Twelve shops around one coordinator, as on the map.
const SHOPS: [number, number][] = [
  [140, 70],
  [250, 40],
  [350, 110],
  [390, 230],
  [330, 350],
  [220, 400],
  [110, 360],
  [40, 260],
  [60, 150],
  [200, 130],
  [290, 250],
  [150, 280],
];
const HUB: [number, number] = [215, 215];

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        background: "#0d0d0d",
        color: INK,
        padding: 64,
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", flex: 1, paddingRight: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <svg width="52" height="52" viewBox="0 0 32 32">
            <path d="M16 2.5 28 9.25v13.5L16 29.5 4 22.75V9.25Z" fill={HONEY} />
            <path
              d="M16 9.5 21.6 12.7v6.6L16 22.5l-5.6-3.2v-6.6Z"
              fill="none"
              stroke="#1c1400"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            <circle cx="16" cy="16" r="1.9" fill="#1c1400" />
          </svg>
          <div style={{ fontSize: 40, fontWeight: 700, letterSpacing: -1 }}>Swarm</div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            marginTop: 56,
            fontSize: 62,
            fontWeight: 700,
            lineHeight: 1.08,
            letterSpacing: -2,
          }}
        >
          <span>Small shops buy alone</span>
          <span>and pay retail.</span>
          <span style={{ color: HONEY }}>Swarm lets them</span>
          <span style={{ color: HONEY }}>buy like a chain.</span>
        </div>
        <div
          style={{
            display: "flex",
            marginTop: "auto",
            fontSize: 26,
            color: SOFT,
            lineHeight: 1.35,
          }}
        >
          AI agents pool a street&apos;s orders, negotiate with suppliers, and settle every cent
          through PayPal.
        </div>
      </div>
      <div style={{ display: "flex", width: 430, alignItems: "center", justifyContent: "center" }}>
        <svg width="430" height="430" viewBox="0 0 430 430">
          {SHOPS.map(([x, y], index) => (
            <line
              key={`l${index}`}
              x1={x}
              y1={y}
              x2={HUB[0]}
              y2={HUB[1]}
              stroke={HONEY}
              strokeOpacity="0.35"
              strokeWidth="2"
            />
          ))}
          {SHOPS.map(([x, y], index) => (
            <circle
              key={`c${index}`}
              cx={x}
              cy={y}
              r="17"
              fill="#1a1a19"
              stroke={index % 3 === 0 ? "#0ca30c" : HONEY}
              strokeWidth="4"
            />
          ))}
          <circle cx={HUB[0]} cy={HUB[1]} r="46" fill={HONEY} fillOpacity="0.18" />
          <path
            d="M215 177 248 196v38l-33 19-33-19v-38Z"
            fill={HONEY}
            stroke="#0d0d0d"
            strokeWidth="3"
          />
        </svg>
      </div>
    </div>,
    size,
  );
}
