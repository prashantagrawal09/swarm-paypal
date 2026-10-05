"use client";

/** Small pill in the header showing whether the backend and database are reachable. */

import { useEffect, useState } from "react";

import { fetchHealth } from "@/lib/api";

type Status = "checking" | "online" | "degraded" | "offline";

const STYLES: Record<Status, { dot: string; label: string }> = {
  checking: { dot: "bg-stone-400", label: "Checking backend" },
  online: { dot: "bg-emerald-500", label: "Backend online" },
  degraded: { dot: "bg-amber-500", label: "Database unavailable" },
  offline: { dot: "bg-rose-500", label: "Backend offline" },
};

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    const check = async () => {
      try {
        const health = await fetchHealth(controller.signal);
        setStatus(health.database === "ok" ? "online" : "degraded");
      } catch {
        if (!controller.signal.aborted) setStatus("offline");
      }
    };
    check();
    const timer = setInterval(check, 15_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  const style = STYLES[status];
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-stone-200 px-3 py-1 text-xs text-stone-600 dark:border-stone-800 dark:text-stone-400">
      <span className={`h-2 w-2 rounded-full ${style.dot}`} aria-hidden />
      {style.label}
    </span>
  );
}
