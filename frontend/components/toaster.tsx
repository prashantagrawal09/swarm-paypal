"use client";

/**
 * Toasts for the moments that matter (a rejected invoice, a short delivery, a refund, a
 * neighbour swap, the week finishing) on every page except the live board, where the
 * narrator already says them.
 */

import {
  AlertTriangle,
  CheckCircle2,
  type LucideIcon,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { useNames } from "@/components/feeds";
import { cx } from "@/components/ui";
import type { DemoState } from "@/lib/api";
import { useLive } from "@/lib/live";
import { describeStory, type Tone } from "@/lib/story";
import { useNow } from "@/lib/use-now";

const SHOW_MS = 6500;
const MAX = 3;

const TONE: Partial<Record<Tone, { chip: string; icon: LucideIcon }>> = {
  good: { chip: "bg-good-soft text-good-ink", icon: CheckCircle2 },
  warning: { chip: "bg-warning-soft text-warning-ink", icon: AlertTriangle },
  critical: { chip: "bg-critical-soft text-critical-ink", icon: ShieldAlert },
  honey: { chip: "bg-honey-soft text-honey-ink", icon: Sparkles },
};

/** Step changes and routine negotiation chatter stay on the board; these earn a toast. */
const TOAST_KINDS = new Set([
  "captured",
  "refunded",
  "invoice_checked",
  "swap_completed",
  "approval_needed",
  "hold_failed",
  "week_summary",
]);

export function Toaster() {
  const pathname = usePathname();
  const { timeline } = useLive();
  const names = useNames();
  const { data: state } = useSWR<DemoState>("/api/demo/state");
  const now = useNow(500);
  const [dismissed, setDismissed] = useState<string[]>([]);

  // The live board and the watch page narrate these moments themselves.
  if (pathname.startsWith("/live") || pathname.startsWith("/watch")) return null;

  const toasts = timeline
    .filter(
      (item) =>
        item.kind === "event" &&
        TOAST_KINDS.has(item.event.kind) &&
        // an approved invoice is good news, but not worth interrupting for
        !(item.event.kind === "invoice_checked" && item.event.approved) &&
        now - item.seenAt < SHOW_MS &&
        !dismissed.includes(item.id),
    )
    .slice(0, MAX)
    .map((item) => ({ item, caption: describeStory(item, names, state?.steps ?? []) }))
    .filter((toast) => toast.caption !== null);

  return (
    <div
      className="pointer-events-none fixed right-4 bottom-4 z-40 flex w-[min(24rem,calc(100vw-2rem))] flex-col-reverse gap-2"
      role="status"
      aria-live="polite"
    >
      <AnimatePresence initial={false}>
        {toasts.map(({ item, caption }) => {
          if (!caption) return null;
          const tone = TONE[caption.tone] ?? TONE.honey!;
          const Icon = tone.icon;
          return (
            <motion.div
              key={item.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className="border-line bg-surface pointer-events-auto flex items-start gap-3 rounded-xl border p-3 shadow-[var(--shadow)]"
            >
              <span
                className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-lg", tone.chip)}
                aria-hidden
              >
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-ink text-sm leading-snug font-medium">{caption.title}</p>
                {caption.detail ? (
                  <p className="text-ink-2 mt-0.5 line-clamp-2 text-xs">{caption.detail}</p>
                ) : null}
                <Link
                  href="/live"
                  className="text-ink-2 hover:text-ink mt-1 inline-block text-xs underline underline-offset-2"
                >
                  See it on the live board
                </Link>
              </div>
              <button
                type="button"
                onClick={() => setDismissed((ids) => [...ids.slice(-20), item.id])}
                className="text-muted hover:text-ink -m-1 rounded p-1"
                aria-label="Dismiss"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
