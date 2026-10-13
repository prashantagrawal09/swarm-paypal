"use client";

/**
 * Where the week's money went, as a flow: each shop's charges (left) pass through Swarm's
 * PayPal balance (middle) to suppliers, neighbours, refunds and the fee (right). Ribbon
 * thickness is the amount. Every node is labelled with its name and amount, so colour only
 * helps the eye follow a ribbon; hover or focus a node to isolate its flows.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Empty } from "@/components/ui";
import type { MoneyFlow } from "@/lib/api";
import { layoutFlow, NODE_W } from "@/lib/flow-layout";
import { money, moneyWhole } from "@/lib/format";
import { useWidth } from "@/lib/use-width";

export function MoneyFlowChart({ flow }: { flow: MoneyFlow }) {
  const router = useRouter();
  const [frame, width] = useWidth<HTMLElement>(0);
  const [focus, setFocus] = useState<string | null>(null);
  const compact = width > 0 && width < 560;
  const height = compact ? 460 : 440;
  const margin = useMemo(
    () => ({ left: compact ? 92 : 168, right: compact ? 112 : 196, top: 34, bottom: 14 }),
    [compact],
  );
  const layout = useMemo(
    () => (width > 0 ? layoutFlow(flow, width, height, margin) : null),
    [flow, width, height, margin],
  );

  if (!flow.charged_cents) {
    return (
      <Empty>
        Nothing has been charged yet. Money starts moving on Thursday, when deliveries arrive.
      </Empty>
    );
  }

  const related = (linkFrom: string, linkTo: string) =>
    focus === null || focus === linkFrom || focus === linkTo;
  const focused = layout?.nodes.find((n) => n.id === focus);
  const short = (label: string) =>
    compact && label.length > 12 ? `${label.slice(0, 11)}…` : label;

  return (
    <figure ref={frame} className="w-full">
      {layout && layout.nodes.length ? (
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="block overflow-visible"
          // Its nodes can be focused, so it is a group, not a single picture.
          role="group"
          aria-label={`Money flow for the week: ${money(flow.charged_cents)} charged to ${flow.shops.length} shops; ${money(flow.suppliers_cents)} paid to suppliers, ${money(flow.fee_cents)} Swarm fee, ${money(flow.refunds_cents)} refunded, ${money(flow.neighbours_cents)} between neighbours.`}
          onPointerLeave={() => setFocus(null)}
        >
          {/* Ribbons */}
          {layout.links.map((link) => (
            <path
              key={link.id}
              d={link.path}
              fill={link.color}
              fillOpacity={related(link.from, link.to) ? (focus ? 0.5 : 0.22) : 0.05}
              style={{ transition: "fill-opacity 200ms ease" }}
            />
          ))}

          {/* Nodes and their labels */}
          {layout.nodes.map((node) => {
            // With a node in focus, everything not on its flows steps back.
            const quiet =
              focus !== null &&
              focus !== "mid" &&
              node.id !== focus &&
              node.id !== "mid" &&
              !layout.links.some(
                (l) =>
                  (l.from === focus && l.to === node.id) || (l.to === focus && l.from === node.id),
              );
            const interactive = {
              tabIndex: 0,
              onPointerEnter: () => setFocus(node.id),
              onFocus: () => setFocus(node.id),
              onBlur: () => setFocus(null),
              onClick: () => (node.href ? router.push(node.href) : undefined),
              onKeyDown: (event: React.KeyboardEvent) => {
                if (event.key === "Enter" && node.href) router.push(node.href);
              },
            };
            if (node.side === "mid") {
              return (
                <g key={node.id} {...interactive} className="outline-none">
                  <rect
                    x={node.x}
                    y={node.y}
                    width={NODE_W}
                    height={node.h}
                    rx={3}
                    fill={node.color}
                  />
                  <text
                    x={node.x + NODE_W / 2}
                    y={node.labelY - 12}
                    textAnchor="middle"
                    className="fill-[var(--ink-2)] text-[11px]"
                  >
                    {compact ? "Via PayPal" : node.label}
                  </text>
                  <text
                    x={node.x + NODE_W / 2}
                    y={node.labelY + 2}
                    textAnchor="middle"
                    className="tabular fill-[var(--ink)] text-[12px] font-semibold"
                  >
                    {money(node.value)}
                  </text>
                </g>
              );
            }
            const left = node.side === "left";
            const labelX = left ? node.x - 8 : node.x + NODE_W + 8;
            const mid = node.y + node.h / 2;
            return (
              <g
                key={node.id}
                {...interactive}
                role={node.href ? "link" : undefined}
                aria-label={`${node.label}: ${money(node.value)}`}
                className={node.href ? "cursor-pointer outline-none" : "outline-none"}
                opacity={quiet ? 0.35 : 1}
                style={{ transition: "opacity 200ms ease" }}
              >
                {/* a generous hit area: the bar plus its label */}
                <rect
                  x={left ? 0 : node.x}
                  y={Math.min(node.y, node.labelY - 9)}
                  width={left ? node.x + NODE_W : width - node.x}
                  height={Math.max(node.h, 16)}
                  fill="transparent"
                />
                <rect
                  x={node.x}
                  y={node.y}
                  width={NODE_W}
                  height={node.h}
                  rx={2.5}
                  fill={node.color}
                />
                {Math.abs(node.labelY - mid) > 4 ? (
                  <line
                    x1={left ? node.x - 2 : node.x + NODE_W + 2}
                    y1={mid}
                    x2={left ? labelX + 2 : labelX - 2}
                    y2={node.labelY}
                    stroke="var(--axis)"
                    strokeWidth={1}
                  />
                ) : null}
                <text
                  x={labelX}
                  y={node.labelY}
                  dy="0.32em"
                  textAnchor={left ? "end" : "start"}
                  className="text-[11px]"
                >
                  <tspan className="fill-[var(--ink-2)]">{short(node.label)}</tspan>
                  <tspan dx={6} className="tabular fill-[var(--ink)] font-medium">
                    {compact ? moneyWhole(node.value) : money(node.value)}
                  </tspan>
                </text>
              </g>
            );
          })}
        </svg>
      ) : (
        <div style={{ height }} aria-hidden />
      )}
      <p className="text-muted mt-1 min-h-4 text-xs" role="status">
        {focused && focused.side !== "mid"
          ? `${focused.label}: ${money(focused.value)}, ${((focused.value / (layout?.total || 1)) * 100).toFixed(1)}% of what was charged.`
          : "Hover or focus a name to follow its money. Ribbon thickness is the amount."}
      </p>
      {flow.owed_cents < 0 ? (
        <p className="text-ink-2 mt-2 text-xs">
          {money(-flow.owed_cents)} was refunded to a shop after its supplier had already been paid
          in full, so the supplier owes that back to Swarm. The ledger records it as owed.
        </p>
      ) : null}
      <figcaption className="sr-only">
        Charged by shop: {flow.shops.map((s) => `${s.name} ${money(s.charged_cents)}`).join(", ")}.
        Paid to suppliers:{" "}
        {flow.suppliers.map((s) => `${s.name} ${money(s.paid_cents)}`).join(", ")}.
      </figcaption>
    </figure>
  );
}
