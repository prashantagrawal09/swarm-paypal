"use client";

/**
 * The negotiation as it happens: one lane per supplier, a dot at its opening quote and a
 * dot at its latest, on a shared price scale (cheaper is to the left). Dots, not bars: the
 * quotes differ by a few percent, which a zero-based bar would hide.
 *
 * Shown only while a group order is being negotiated, and for a few seconds after the award.
 */

import { ArrowLeft, Gavel, Trophy } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { useNames } from "@/components/feeds";
import { AnimatedNumber } from "@/components/stats";
import { cx, StatusPill } from "@/components/ui";
import type { GroupOrder } from "@/lib/api";
import { agentName, CATEGORY_EMOJI, CATEGORY_LABEL, money, slotColor } from "@/lib/format";
import { useLive } from "@/lib/live";
import { lanes } from "@/lib/negotiation";
import { useNow } from "@/lib/use-now";

const LINGER_MS = 9000;

export function NegotiationSpotlight({ groups }: { groups: GroupOrder[] }) {
  const { messages, lastAward } = useLive();
  const names = useNames();
  const now = useNow(1000);

  // The order being negotiated, or the one awarded a moment ago while this page was open.
  const negotiating = groups.find((g) => g.status === "NEGOTIATING");
  const justAwarded =
    lastAward && now - lastAward.at < LINGER_MS
      ? groups.find((g) => g.conversation_id === lastAward.conversation)
      : undefined;
  const group = negotiating ?? justAwarded;

  return (
    <AnimatePresence initial={false}>
      {group ? (
        <motion.section
          key="spotlight"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="overflow-hidden"
          aria-label="Live negotiation"
        >
          <Spotlight
            group={group}
            last={[...messages].reverse().find((m) => m.conversation_id === group.conversation_id)}
            names={names}
          />
        </motion.section>
      ) : null}
    </AnimatePresence>
  );
}

function Spotlight({
  group,
  last,
  names,
}: {
  group: GroupOrder;
  last?: { from: string; text: string; type: string };
  names: Record<string, string>;
}) {
  const rows = lanes(group);
  const awarded = group.status !== "NEGOTIATING" && group.supplier !== null;
  const round = Math.max(0, ...rows.map((r) => r.round));
  const prices = rows.flatMap((r) => [r.opening, r.latest]);
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  const pad = Math.max(200, (hi - lo) * 0.18);
  const min = lo - pad;
  const max = hi + pad;
  const at = (cents: number) => `${((cents - min) / (max - min)) * 100}%`;
  const best = rows.length ? Math.min(...rows.map((r) => r.latest)) : 0;
  const winner = awarded ? group.supplier?.code : undefined;

  return (
    <div className="border-honey/50 bg-surface rounded-2xl border shadow-[var(--shadow)]">
      <header className="flex items-start gap-3 px-5 pt-4">
        <span
          className="bg-honey grid h-9 w-9 shrink-0 place-items-center rounded-xl text-[#1c1400]"
          aria-hidden
        >
          {awarded ? <Trophy className="h-4 w-4" /> : <Gavel className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-ink text-sm font-semibold">
              {awarded ? "Awarded" : "Negotiating now"}:{" "}
              <span aria-hidden>{CATEGORY_EMOJI[group.category]}</span>{" "}
              {CATEGORY_LABEL[group.category] ?? group.category}
            </h2>
            {awarded ? (
              <StatusPill tone="good">{group.supplier?.name} won</StatusPill>
            ) : (
              <StatusPill tone="busy">
                {round ? `Round ${round} of 3` : "Quotes requested"}
              </StatusPill>
            )}
          </div>
          <p className="text-ink-2 mt-0.5 line-clamp-1 text-xs" title={group.pooled_text}>
            {group.shops} shops, one order: {group.pooled_text}
          </p>
        </div>
      </header>

      {rows.length ? (
        <div className="px-5 pt-3 pb-1">
          <ul className="space-y-2.5">
            {rows.map((lane) => {
              const leading = winner ? lane.code === winner : lane.latest === best;
              const drop = lane.opening - lane.latest;
              return (
                <li
                  key={lane.code}
                  className="grid grid-cols-[7.5rem_1fr_6.5rem] items-center gap-3"
                >
                  <span className="text-ink-2 flex min-w-0 items-center gap-1.5 text-xs">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: slotColor(lane.code) }}
                      aria-hidden
                    />
                    <span className={cx("truncate", leading && "text-ink font-semibold")}>
                      {lane.name}
                    </span>
                  </span>
                  <div
                    className="relative h-5"
                    role="img"
                    aria-label={`${lane.name}: opened at ${money(lane.opening)}, now ${money(lane.latest)}`}
                  >
                    <div className="bg-grid absolute top-1/2 h-px w-full" />
                    {/* the drop from the opening quote */}
                    <div
                      className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full opacity-60 transition-all duration-700 ease-out"
                      style={{
                        left: at(lane.latest),
                        width: `calc(${at(lane.opening)} - ${at(lane.latest)})`,
                        background: slotColor(lane.code),
                      }}
                    />
                    <span
                      className="bg-surface absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition-all duration-700 ease-out"
                      style={{ left: at(lane.opening), borderColor: slotColor(lane.code) }}
                    />
                    <span
                      className={cx(
                        "ring-surface absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 transition-all duration-700 ease-out",
                        leading ? "h-4 w-4" : "h-3 w-3",
                      )}
                      style={{ left: at(lane.latest), background: slotColor(lane.code) }}
                    />
                  </div>
                  <span className="text-right">
                    <span className="tabular text-ink block text-sm font-semibold">
                      <AnimatedNumber value={lane.latest} format={money} />
                    </span>
                    <span className="tabular text-muted block text-[11px]">
                      {drop > 0 ? `−${money(drop)}` : `round ${lane.round}`}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="text-muted mt-2 grid grid-cols-[7.5rem_1fr_6.5rem] gap-3 text-[10px]">
            <span />
            <span className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1">
                <ArrowLeft className="h-3 w-3" aria-hidden /> cheaper
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="inline-flex items-center gap-1">
                  <span className="border-ink-2 h-2 w-2 rounded-full border-2" aria-hidden />{" "}
                  opening
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="bg-ink-2 h-2 w-2 rounded-full" aria-hidden /> latest
                </span>
              </span>
            </span>
            <span className="text-right">landed price</span>
          </div>
        </div>
      ) : (
        <p className="text-muted px-5 pt-3 text-sm">Waiting for the first quotes...</p>
      )}

      <p
        className="border-line text-ink-2 mx-5 mt-3 mb-4 line-clamp-2 border-t pt-3 text-xs"
        aria-live="polite"
      >
        {last ? (
          <>
            <span className="text-ink font-medium">{agentName(last.from, names)}:</span> {last.text}
          </>
        ) : (
          "The coordinator tells each supplier only the best competing price, never whose it is."
        )}
      </p>
    </div>
  );
}
