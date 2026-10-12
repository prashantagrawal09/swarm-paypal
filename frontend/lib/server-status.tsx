"use client";

/**
 * Whether the API has answered yet. A free hosting plan puts the server to sleep when
 * nobody is visiting and takes up to a minute to wake it, so "not yet" is a normal state
 * that deserves a proper screen rather than empty pages.
 */

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { fetchHealth } from "@/lib/api";

/** `checking`: just loaded, no answer yet. `waking`: still no answer after a moment. */
export type ServerStatus = "checking" | "up" | "waking";

const SLOW_MS = 1500;
const ATTEMPT_MS = 10_000;
const RETRY_MS = 2000;

type Value = { status: ServerStatus; waitingSince: number | null };

const ServerStatusContext = createContext<Value>({ status: "up", waitingSince: null });

export function useServerStatus(): Value {
  return useContext(ServerStatusContext);
}

/** True for an API on this machine, where "not answering" means it isn't running. */
export function isLocalUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
  } catch {
    return false;
  }
}

/** How far along a wake-up is, as 0 to 1: quick at first, never quite reaching the end. */
export function wakeProgress(elapsedMs: number, typicalMs = 50_000): number {
  if (elapsedMs <= 0) return 0;
  return Math.min(0.97, 1 - Math.exp((-2.2 * elapsedMs) / typicalMs));
}

export function ServerStatusProvider({ children }: { children: React.ReactNode }) {
  const [value, setValue] = useState<Value>({ status: "checking", waitingSince: null });
  const { mutate } = useSWRConfig();
  const waited = useRef(false);

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();

    const markWaking = () => {
      if (stopped) return;
      waited.current = true;
      setValue((v) =>
        v.status === "checking" ? { status: "waking", waitingSince: startedAt } : v,
      );
    };
    const slow = setTimeout(markWaking, SLOW_MS);

    const attempt = async () => {
      try {
        await fetchHealth(AbortSignal.timeout(ATTEMPT_MS));
        if (stopped) return;
        clearTimeout(slow);
        setValue({ status: "up", waitingSince: null });
        // Anything that was asked for while the server slept gets asked again.
        if (waited.current) void mutate(() => true);
      } catch {
        if (stopped) return;
        markWaking();
        retry = setTimeout(attempt, RETRY_MS);
      }
    };
    void attempt();

    return () => {
      stopped = true;
      clearTimeout(slow);
      clearTimeout(retry);
    };
  }, [mutate]);

  return <ServerStatusContext.Provider value={value}>{children}</ServerStatusContext.Provider>;
}
