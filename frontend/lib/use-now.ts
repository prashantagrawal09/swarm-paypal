"use client";

import { useEffect, useState } from "react";

/** The current time, refreshed every `intervalMs`, for fading things that happened recently. */
export function useNow(intervalMs = 500): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
