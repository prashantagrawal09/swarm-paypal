"use client";

/**
 * A PayPal hold as one bar: the part that was charged (solid) and the part that went back
 * (hatched, so the two don't rely on colour alone). The numbers belong beside it, in text.
 */

import { useId } from "react";

import { cx } from "@/components/ui";

export function HoldBar({
  holdCents,
  chargedCents,
  label,
  className,
}: {
  holdCents: number;
  chargedCents: number;
  /** Read by screen readers in place of the picture. */
  label: string;
  className?: string;
}) {
  const id = useId();
  const share = holdCents > 0 ? Math.max(0, Math.min(100, (chargedCents / holdCents) * 100)) : 0;
  const split = chargedCents > 0 && chargedCents < holdCents;
  return (
    <svg
      className={cx("block h-9 w-full", className)}
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      <defs>
        <pattern
          id={id}
          width="7"
          height="7"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <rect width="7" height="7" fill="var(--warning-soft)" />
          <line x1="0" y1="0" x2="0" y2="7" stroke="var(--warning)" strokeWidth="2.5" />
        </pattern>
        <clipPath id={`${id}-round`}>
          <rect width="100%" height="100%" rx="8" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-round)`}>
        <rect width="100%" height="100%" fill={`url(#${id})`} />
        <rect
          height="100%"
          fill="var(--good)"
          style={{ width: `${share}%`, transition: "width 260ms ease-out" }}
        />
        {/* a surface-coloured gap between the two parts */}
        <rect
          height="100%"
          width="2"
          fill="var(--surface)"
          style={{
            transform: `translateX(calc(${share}% - 1px))`,
            transition: "transform 260ms ease-out",
            opacity: split ? 1 : 0,
          }}
        />
      </g>
    </svg>
  );
}
