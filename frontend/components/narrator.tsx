"use client";

/**
 * The narrator: one plain sentence about what is happening right now, with the buttons to
 * run the week, so the live board works on its own in a single window.
 */

import {
  AlertTriangle,
  CalendarCheck,
  CheckCircle2,
  FastForward,
  Handshake,
  type LucideIcon,
  PackageCheck,
  Repeat2,
  RotateCcw,
  ShieldAlert,
  Siren,
  SkipForward,
  Sparkles,
  Sunrise,
  Wallet,
} from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { useSWRConfig } from "swr";

import { DemoKeyPrompt } from "@/components/demo-key-prompt";
import { useNames } from "@/components/feeds";
import { Button, cx } from "@/components/ui";
import { ApiError, type Overview, post } from "@/lib/api";
import { useLive } from "@/lib/live";
import { currentCaption, type Tone } from "@/lib/story";

export const STEP_ICON: Record<string, LucideIcon> = {
  forecasts: Sunrise,
  negotiation: Handshake,
  holds: Wallet,
  delivery: PackageCheck,
  settlement: CheckCircle2,
  surplus: Repeat2,
  emergency: Siren,
  report: CalendarCheck,
};

export const TONE: Record<Tone, { chip: string; icon?: LucideIcon }> = {
  neutral: { chip: "bg-surface-2 text-ink" },
  honey: { chip: "bg-honey text-[#1c1400]" },
  good: { chip: "bg-good-soft text-good-ink", icon: CheckCircle2 },
  warning: { chip: "bg-warning-soft text-warning-ink", icon: AlertTriangle },
  critical: { chip: "bg-critical-soft text-critical-ink", icon: ShieldAlert },
};

export function Narrator({ overview }: { overview: Overview }) {
  const { timeline } = useLive();
  const names = useNames();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // The action that was refused for want of the demo key; it runs once the key is entered.
  const [refused, setRefused] = useState<{ label: string; paths: string[] } | null>(null);

  // "/live?play=1" (the landing page's button) starts the week once. The flag is dropped
  // only when the run is kicked off, so a refresh doesn't start it again and a re-run of
  // this effect (React runs effects twice in development) doesn't lose it.
  useEffect(() => {
    if (!new URLSearchParams(window.location.search).has("play")) return;
    const timer = setTimeout(() => {
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
      if (overview.running || !overview.demo_mode) return;
      const finishedNow = overview.steps.every((s) => s.status === "done");
      void (finishedNow
        ? act("again", "/api/demo/reset", "/api/demo/run-week")
        : act("run", "/api/demo/run-week"));
    }, 600);
    return () => clearTimeout(timer);
    // Once per page load; `act` and `overview` are read at that moment on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { caption, id } = currentCaption(timeline, names, overview);
  const tone = TONE[caption.tone];
  const Icon = tone.icon ?? (caption.step ? STEP_ICON[caption.step] : undefined) ?? Sparkles;

  const done = overview.steps.filter((s) => s.status === "done").length;
  const next = overview.steps.find((s) => s.status === "next");
  const finished = done === overview.steps.length;
  // The number goes with the caption: between steps the caption is still about the one
  // that just finished, and "Step 2" next to Monday's caption would contradict it.
  const captioned = caption.step ? overview.steps.findIndex((s) => s.key === caption.step) : -1;
  const stepNumber = captioned >= 0 ? captioned + 1 : Math.min(done + 1, overview.steps.length);
  const locked = overview.running || busy !== null;

  async function act(label: string, ...paths: string[]) {
    setBusy(label);
    setProblem(null);
    setRefused(null);
    try {
      for (const path of paths) await post(path);
      await mutate((key) => typeof key === "string" && key.startsWith("/api/"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setRefused({ label, paths });
      else setProblem(err instanceof Error ? err.message : "That didn't work.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3.5">
        <span
          className={cx(
            "relative grid h-11 w-11 shrink-0 place-items-center rounded-2xl transition-colors duration-500",
            tone.chip,
          )}
          aria-hidden
        >
          <Icon className="h-5 w-5" />
          {overview.running ? (
            <span className="border-honey absolute inset-0 animate-ping rounded-2xl border-2 opacity-40" />
          ) : null}
        </span>
        <div className="min-h-[7.5rem] min-w-0 flex-1 sm:min-h-[5.5rem]" aria-live="polite">
          <div className="text-muted flex flex-wrap items-center gap-x-2 text-[11px] font-medium tracking-wide uppercase">
            <span className="tabular">{overview.local}</span>
            <span aria-hidden>·</span>
            <span>
              {finished ? "Week complete" : `Step ${stepNumber} of ${overview.steps.length}`}
              {overview.running ? " · running" : ""}
            </span>
          </div>
          {/* Keyed, enter-only: captions can change several times a second, and waiting
              for exit animations would let a stale one linger. */}
          <motion.div
            key={id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <p className="text-ink mt-0.5 text-base leading-snug font-semibold text-balance sm:text-lg">
              {caption.title}
            </p>
            {caption.detail ? (
              <p className="text-ink-2 mt-0.5 line-clamp-2 text-sm">{caption.detail}</p>
            ) : null}
          </motion.div>
          {problem ? <p className="text-critical-ink mt-1.5 text-xs">{problem}</p> : null}
          {refused ? (
            <DemoKeyPrompt
              className="mt-2 max-w-xl"
              onSaved={() => void act(refused.label, ...refused.paths)}
            />
          ) : null}
        </div>
      </div>

      {overview.demo_mode ? (
        <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">
          {finished ? (
            <Button
              variant="honey"
              busy={busy === "again"}
              disabled={locked}
              onClick={() => act("again", "/api/demo/reset", "/api/demo/run-week")}
            >
              <RotateCcw className="h-4 w-4" aria-hidden /> Run the week again
            </Button>
          ) : (
            <>
              <Button
                variant="honey"
                busy={busy === "run" || overview.running}
                disabled={locked}
                onClick={() => act("run", "/api/demo/run-week")}
              >
                <FastForward className="h-4 w-4" aria-hidden />
                {overview.running ? "Running" : done === 0 ? "Run the week" : "Run the rest"}
              </Button>
              <Button
                busy={busy === "step"}
                disabled={locked}
                onClick={() => act("step", "/api/demo/advance?paced=true")}
                title={next ? `${next.title}: ${next.description}` : undefined}
              >
                <SkipForward className="h-4 w-4" aria-hidden /> One step
              </Button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
