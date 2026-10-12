/**
 * Layout for the money-flow diagram: who was charged (left), Swarm's PayPal balance
 * (middle), and where the money went (right). Pure geometry, no React.
 *
 * One scale for all three columns, so a ribbon is as thick as its amount everywhere and the
 * middle bar is exactly as tall as everything flowing through it.
 */

import type { MoneyFlow } from "@/lib/api";
import { slotColor } from "@/lib/format";

export type FlowNode = {
  id: string;
  label: string;
  value: number;
  side: "left" | "mid" | "right";
  x: number;
  y: number;
  h: number;
  color: string;
  /** Where the label's baseline goes (pushed apart so small nodes stay readable). */
  labelY: number;
  href?: string;
};

export type FlowLink = {
  id: string;
  from: string;
  to: string;
  value: number;
  color: string;
  path: string;
};

export type FlowLayout = { nodes: FlowNode[]; links: FlowLink[]; total: number };

export const NODE_W = 10;
const LEFT_GAP = 5;
const RIGHT_GAP = 16;
const LABEL_GAP = 15;

type Sink = { id: string; label: string; value: number; color: string; href?: string };

/** Where the money went, in a fixed order (suppliers by code, then the rest). */
export function sinks(flow: MoneyFlow): Sink[] {
  const list: Sink[] = [...flow.suppliers]
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((s) => ({
      id: `supplier:${s.code}`,
      label: s.name,
      value: s.paid_cents,
      color: slotColor(s.code),
      href: `/supplier/${s.code}`,
    }));
  list.push(
    { id: "owed", label: "Still owed to suppliers", value: flow.owed_cents, color: "var(--muted)" },
    {
      id: "neighbours",
      label: "Neighbours (swaps)",
      value: flow.neighbours_cents,
      color: "var(--ink-2)",
    },
    { id: "refunds", label: "Refunds", value: flow.refunds_cents, color: "var(--warning)" },
    { id: "fee", label: "Swarm fee", value: flow.fee_cents, color: "var(--honey)" },
  );
  return list.filter((s) => s.value > 0);
}

function ribbon(x0: number, y0: number, x1: number, y1: number, h: number): string {
  const xm = (x0 + x1) / 2;
  const t = Math.max(h, 1.25); // keep hairline flows visible
  return [
    `M${x0},${y0}`,
    `C${xm},${y0} ${xm},${y1} ${x1},${y1}`,
    `L${x1},${y1 + t}`,
    `C${xm},${y1 + t} ${xm},${y0 + t} ${x0},${y0 + t}`,
    "Z",
  ].join(" ");
}

/** Pushes label positions apart (top to bottom) so none sit closer than `gap`. */
export function spread(ys: number[], gap: number, max: number): number[] {
  const out = [...ys];
  for (let i = 1; i < out.length; i++) out[i] = Math.max(out[i], out[i - 1] + gap);
  // If the last label fell off the bottom, shift the tail back up.
  const overflow = out.length ? out[out.length - 1] - max : 0;
  if (overflow > 0) {
    out[out.length - 1] -= overflow;
    for (let i = out.length - 2; i >= 0; i--) out[i] = Math.min(out[i], out[i + 1] - gap);
  }
  return out;
}

export function layoutFlow(
  flow: MoneyFlow,
  width: number,
  height: number,
  margin: { left: number; right: number; top: number; bottom: number },
): FlowLayout {
  const sources = flow.shops
    .filter((s) => s.charged_cents > 0)
    .sort((a, b) => b.charged_cents - a.charged_cents);
  const targets = sinks(flow);
  const total = sources.reduce((sum, s) => sum + s.charged_cents, 0);
  if (!total || !targets.length) return { nodes: [], links: [], total: 0 };

  const inner = height - margin.top - margin.bottom;
  const scale = Math.min(
    (inner - LEFT_GAP * (sources.length - 1)) / total,
    (inner - RIGHT_GAP * (targets.length - 1)) / total,
  );
  const xLeft = margin.left;
  const xRight = width - margin.right - NODE_W;
  const xMid = (xLeft + xRight) / 2;
  const midH = total * scale;
  const midY = margin.top + (inner - midH) / 2;

  const nodes: FlowNode[] = [];
  const links: FlowLink[] = [];

  // Left: one node per shop, each flowing into the middle in the same order.
  const leftH = total * scale + LEFT_GAP * (sources.length - 1);
  let y = margin.top + (inner - leftH) / 2;
  let into = midY;
  const leftNodes: FlowNode[] = [];
  for (const shop of sources) {
    const h = shop.charged_cents * scale;
    const node: FlowNode = {
      id: `shop:${shop.code}`,
      label: shop.name,
      value: shop.charged_cents,
      side: "left",
      x: xLeft,
      y,
      h,
      color: "var(--ink-2)",
      labelY: y + h / 2,
      href: `/shop/${shop.code}`,
    };
    leftNodes.push(node);
    links.push({
      id: `${node.id}>mid`,
      from: node.id,
      to: "mid",
      value: shop.charged_cents,
      color: "var(--ink-2)",
      path: ribbon(xLeft + NODE_W, y, xMid, into, h),
    });
    y += h + LEFT_GAP;
    into += h;
  }

  // Right: suppliers, neighbours, refunds, fee, each fed from the middle in order.
  const rightH = total * scale + RIGHT_GAP * (targets.length - 1);
  y = margin.top + (inner - rightH) / 2;
  let out = midY;
  const rightNodes: FlowNode[] = [];
  for (const sink of targets) {
    const h = sink.value * scale;
    const node: FlowNode = {
      id: sink.id,
      label: sink.label,
      value: sink.value,
      side: "right",
      x: xRight,
      y,
      h: Math.max(h, 2),
      color: sink.color,
      labelY: y + h / 2,
      href: sink.href,
    };
    rightNodes.push(node);
    links.push({
      id: `mid>${sink.id}`,
      from: "mid",
      to: sink.id,
      value: sink.value,
      color: sink.color,
      path: ribbon(xMid + NODE_W, out, xRight, y, h),
    });
    y += h + RIGHT_GAP;
    out += h;
  }

  for (const column of [leftNodes, rightNodes]) {
    const ys = spread(
      column.map((n) => n.labelY),
      LABEL_GAP,
      height - margin.bottom,
    );
    column.forEach((node, index) => (node.labelY = ys[index]));
  }

  nodes.push(
    ...leftNodes,
    {
      id: "mid",
      label: "Charged through PayPal",
      value: total,
      side: "mid",
      x: xMid,
      y: midY,
      h: midH,
      color: "var(--ink)",
      labelY: midY - 10,
    },
    ...rightNodes,
  );
  return { nodes, links, total };
}
