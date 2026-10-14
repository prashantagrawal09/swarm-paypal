"use client";

/** Hero figure and stat tiles (figures, not charts). */

import { useEffect, useRef, useState } from "react";

import { cx } from "@/components/ui";

/** Animates from the previous value to the new one; respects reduced motion. */
export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(target);
  const shown = useRef(target);

  useEffect(() => {
    const start = shown.current;
    if (start === target) return;
    const span = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : duration;
    let frame = 0;
    const began = performance.now();
    const tick = (now: number) => {
      const t = span === 0 ? 1 : Math.min(1, (now - began) / span);
      const eased = 1 - Math.pow(1 - t, 3);
      shown.current = Math.round(start + (target - start) * eased);
      setValue(shown.current);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return value;
}

export function HeroFigure({
  label,
  value,
  format,
  detail,
}: {
  label: string;
  value: number;
  format: (value: number) => string;
  detail?: React.ReactNode;
}) {
  const shown = useCountUp(value);
  return (
    <div>
      <div className="text-ink-2 text-xs font-medium">{label}</div>
      <div className="text-ink mt-1 text-5xl font-semibold tracking-tight sm:text-6xl">
        {format(shown)}
      </div>
      {detail ? <div className="text-ink-2 mt-1.5 text-sm">{detail}</div> : null}
    </div>
  );
}

export function StatTile({
  label,
  value,
  detail,
  accent,
  className,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  accent?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("border-line bg-surface min-w-0 rounded-xl border px-4 py-3", className)}>
      <div className="text-ink-2 flex items-center justify-between gap-2 text-xs font-medium">
        <span className="truncate">{label}</span>
        {accent}
      </div>
      <div className="text-ink mt-1 truncate text-xl font-semibold tracking-tight">{value}</div>
      {/* Two short lines rather than one cut off: on a phone the tiles are narrow. */}
      {detail ? <div className="text-muted mt-0.5 line-clamp-2 text-xs">{detail}</div> : null}
    </div>
  );
}

export function AnimatedNumber({
  value,
  format,
}: {
  value: number;
  format: (v: number) => string;
}) {
  return <>{format(useCountUp(value))}</>;
}
