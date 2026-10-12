"use client";

import { useEffect, useState } from "react";

/**
 * A number that travels from `from` to `to` once (ease-in-out), and again whenever the
 * target changes. With reduced motion it jumps straight to the end.
 */
export function useTween(from: number, to: number, duration = 1600): number {
  const [value, setValue] = useState(from);

  useEffect(() => {
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const began = performance.now();
    let frame = requestAnimationFrame(function tick(now: number) {
      const t = still ? 1 : Math.min(1, (now - began) / duration);
      const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      setValue(t >= 1 ? to : from + (to - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [from, to, duration]);

  return value;
}
