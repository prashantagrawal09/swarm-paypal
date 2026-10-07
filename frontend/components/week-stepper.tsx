"use client";

/** The Swarm week as eight steps, Monday to Sunday: done, happening next, still to come. */

import { Check, Loader2 } from "lucide-react";

import { cx } from "@/components/ui";
import type { Step } from "@/lib/api";
import { dayTime } from "@/lib/format";
import { useLive } from "@/lib/live";

export function WeekStepper({ steps, running }: { steps: Step[]; running: boolean }) {
  const { events } = useLive();
  const lastStep = events.find((e) => e.kind === "step_started" || e.kind === "step_finished");
  const inProgress = lastStep?.kind === "step_started" ? String(lastStep.step) : null;

  return (
    <ol className="grid grid-cols-4 gap-x-2 gap-y-4 sm:grid-cols-8" aria-label="This Swarm week">
      {steps.map((step, index) => {
        const busy =
          running && (inProgress === step.key || (!inProgress && step.status === "next"));
        const done = step.status === "done";
        return (
          <li
            key={step.key}
            className="relative min-w-0"
            aria-current={step.status === "next" ? "step" : undefined}
          >
            {index > 0 ? (
              <span
                className={cx(
                  "absolute top-3.5 right-1/2 -z-0 hidden h-0.5 w-full -translate-y-1/2 sm:block",
                  done || step.status === "next" ? "bg-honey" : "bg-line",
                )}
                aria-hidden
              />
            ) : null}
            <div className="relative flex flex-col items-center text-center">
              <span
                className={cx(
                  "grid h-7 w-7 place-items-center rounded-full border-2 text-[11px] font-semibold transition-colors",
                  done && "border-honey bg-honey text-[#1c1400]",
                  step.status === "next" && "border-honey bg-surface text-honey-ink",
                  step.status === "pending" && "border-line-strong bg-surface text-muted",
                )}
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-label="running" />
                ) : done ? (
                  <Check className="h-3.5 w-3.5" aria-label="done" />
                ) : (
                  index + 1
                )}
              </span>
              <span
                className={cx(
                  "mt-1.5 line-clamp-2 text-[11px] leading-tight font-medium",
                  step.status === "pending" ? "text-muted" : "text-ink",
                )}
                title={step.description}
              >
                {step.title}
              </span>
              <span className="tabular text-muted mt-0.5 text-[10px]">{dayTime(step.at)}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
