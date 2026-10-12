"use client";

/**
 * Shown in place of a data page while the API hasn't answered: on a hosted demo the server
 * is waking from sleep; on a laptop it simply isn't running.
 */

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { cx } from "@/components/ui";
import { API_URL } from "@/lib/api";
import { isLocalUrl, useServerStatus, wakeProgress } from "@/lib/server-status";
import { useNow } from "@/lib/use-now";

/** Pages that read well without the API (their live parts say they are waiting). */
const STATIC_PAGES = new Set(["/"]);

export function ServerGate({ children }: { children: React.ReactNode }) {
  const { status } = useServerStatus();
  const pathname = usePathname();
  if (status !== "waking" || STATIC_PAGES.has(pathname)) return <>{children}</>;
  return (
    <Suspense fallback={<WakeScreen />}>
      <WakeScreenForPage />
    </Suspense>
  );
}

function WakeScreenForPage() {
  const params = useSearchParams();
  return <WakeScreen willPlay={params.has("play")} />;
}

export function WakeScreen({
  willPlay = false,
  compact = false,
}: {
  willPlay?: boolean;
  /** Inside a card: no page-sized padding, and a paragraph instead of the page heading. */
  compact?: boolean;
}) {
  const { waitingSince } = useServerStatus();
  const now = useNow(250);
  const elapsed = waitingSince ? Math.max(0, now - waitingSince) : 0;
  const seconds = Math.floor(elapsed / 1000);
  const local = isLocalUrl(API_URL);

  return (
    <div
      className={cx(
        "mx-auto flex w-full max-w-xl flex-col items-center justify-center px-6 text-center",
        compact ? "py-6" : "flex-1 py-20",
      )}
    >
      <Hive />
      {local ? (
        <>
          <Heading compact={compact}>The Swarm backend isn&apos;t answering</Heading>
          <p className={cx("text-ink-2 mt-2 text-sm", compact && "text-xs")}>
            Start it with{" "}
            <code className="bg-surface-2 rounded px-1.5 py-0.5 font-mono">make backend</code>. This
            page carries on by itself as soon as it is up.
          </p>
        </>
      ) : (
        <>
          <Heading compact={compact}>Waking the demo server</Heading>
          {compact ? null : (
            <p className="text-ink-2 mt-2 text-sm text-balance">
              This demo runs on a free server that sleeps when nobody is visiting. Waking it takes
              up to a minute.{" "}
              {willPlay
                ? "The week starts by itself as soon as it is up."
                : "This page carries on by itself as soon as it is up."}
            </p>
          )}
          <div
            className={cx(
              "bg-surface-2 h-1.5 w-full max-w-xs overflow-hidden rounded-full",
              compact ? "mt-4" : "mt-6",
            )}
            role="progressbar"
            aria-label="Waking the demo server"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(wakeProgress(elapsed) * 100)}
          >
            <div
              className="bg-honey h-full rounded-full transition-[width] duration-300 ease-out"
              style={{ width: `${wakeProgress(elapsed) * 100}%` }}
            />
          </div>
          <p className="text-muted tabular mt-2 text-xs" aria-live="off">
            {seconds < 75
              ? `${seconds} s`
              : `${seconds} s. Longer than usual; it keeps trying, or try again in a few minutes.`}
          </p>
        </>
      )}
    </div>
  );
}

function Heading({ compact, children }: { compact: boolean; children: React.ReactNode }) {
  const Tag = compact ? "p" : "h1";
  return (
    <Tag
      className={cx(
        "text-ink font-semibold tracking-tight",
        compact ? "mt-5 text-base" : "mt-8 text-xl",
      )}
    >
      {children}
    </Tag>
  );
}

/** Seven cells of honeycomb, lighting up in turn. */
function Hive() {
  const cells = [
    [0, 0],
    [1, 0],
    [0.5, 0.87],
    [-0.5, 0.87],
    [-1, 0],
    [-0.5, -0.87],
    [0.5, -0.87],
  ];
  return (
    <svg viewBox="-60 -56 120 112" className="h-24 w-24" aria-hidden>
      {cells.map(([cx, cy], index) => (
        <polygon
          key={index}
          points="0,-17 14.7,-8.5 14.7,8.5 0,17 -14.7,8.5 -14.7,-8.5"
          transform={`translate(${cx * 31} ${cy * 31})`}
          className="hive-cell fill-honey"
          style={{ animationDelay: `${index * 160}ms` }}
        />
      ))}
    </svg>
  );
}
