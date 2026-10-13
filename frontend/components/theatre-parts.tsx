"use client";

/** The pieces of the watch page: day strip, controls, tally, negotiation, title card, finale. */

import {
  ArrowRight,
  BookCheck,
  CheckCircle2,
  Keyboard,
  Leaf,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RotateCcw,
  ShieldAlert,
  SkipBack,
  SkipForward,
  Trophy,
  Undo2,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";

import { AnimatedNumber } from "@/components/stats";
import { cx } from "@/components/ui";
import type { AgentMessage, Step } from "@/lib/api";
import { agentName, CATEGORY_LABEL, kg, money, moneyWhole, slotColor } from "@/lib/format";
import type { PayPalEvent } from "@/lib/live";
import { SPEEDS, type Speed } from "@/lib/replay";
import type { Negotiation, StepProgress, World } from "@/lib/world-state";

// ---------------------------------------------------------------------------------------
// Day strip
// ---------------------------------------------------------------------------------------

/** "Wednesday: PayPal holds" -> ["Wed", "PayPal holds"]. */
export function splitTitle(title: string): [string, string] {
  const [day, ...rest] = title.split(":");
  const what = rest.join(":").trim();
  return [day.trim().slice(0, 3), what ? what.charAt(0).toUpperCase() + what.slice(1) : ""];
}

/** One word per step, short enough for eight to sit side by side. */
const SHORT: Record<string, string> = {
  forecasts: "Forecasts",
  negotiation: "Negotiation",
  holds: "Holds",
  delivery: "Delivery",
  settlement: "Settlement",
  surplus: "Swap",
  emergency: "Emergency",
  report: "Report",
};

export function DayStrip({
  steps,
  progress,
  onPick,
}: {
  steps: Step[];
  progress: Record<string, StepProgress>;
  /** Jump to a step that is in the recording (undefined for steps not recorded yet). */
  onPick: (step: string) => void;
}) {
  return (
    <ol
      className="flex min-w-0 items-stretch gap-0.5 overflow-x-auto"
      aria-label="The week, day by day"
    >
      {steps.map((step) => {
        const state = progress[step.key] ?? "pending";
        const [day] = splitTitle(step.title);
        const what = SHORT[step.key] ?? splitTitle(step.title)[1];
        return (
          <li key={step.key} className="min-w-0 flex-1">
            <button
              type="button"
              onClick={() => onPick(step.key)}
              disabled={state === "pending"}
              aria-current={state === "running" ? "step" : undefined}
              title={`${step.title}: ${step.description}`}
              className={cx(
                // On a phone there is room for the day only; the step's name is in the caption.
                "group flex h-full w-full flex-col items-center rounded-lg px-1 py-1.5 transition sm:min-w-[4.25rem] sm:items-start sm:px-1.5 sm:text-left",
                state === "running" && "bg-honey text-[#1c1400]",
                state === "done" && "text-ink hover:bg-surface-2",
                state === "pending" && "text-muted cursor-default",
              )}
            >
              <span className="flex items-center gap-1 text-[10px] font-semibold tracking-wider uppercase">
                {day}
                {state === "done" ? (
                  <CheckCircle2 className="h-3 w-3 opacity-70" aria-hidden />
                ) : null}
              </span>
              <span className="hidden max-w-full truncate text-[11px] font-medium sm:block">
                {what}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------------------

function IconButton({
  label,
  onClick,
  children,
  active = false,
  disabled = false,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cx(
        "grid h-9 min-w-9 place-items-center rounded-lg px-2 text-sm font-medium transition disabled:opacity-40",
        active ? "bg-ink text-page" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

export function Controls({
  playing,
  speed,
  live,
  fullscreen,
  onToggle,
  onSpeed,
  onSkip,
  onRestart,
  onFullscreen,
  onHelp,
}: {
  playing: boolean;
  speed: Speed;
  /** Following a week that is running now: there is nothing to skip through or speed up. */
  live: boolean;
  fullscreen: boolean;
  onToggle: () => void;
  onSpeed: (speed: Speed) => void;
  onSkip: (direction: 1 | -1) => void;
  onRestart: () => void;
  onFullscreen: () => void;
  onHelp: () => void;
}) {
  return (
    <div className="flex items-center gap-0.5" role="group" aria-label="Playback">
      {live ? null : (
        <>
          <span className="hidden sm:contents">
            <IconButton label="Start again (R)" onClick={onRestart}>
              <RotateCcw className="h-4 w-4" aria-hidden />
            </IconButton>
          </span>
          <IconButton label="Previous day (left arrow)" onClick={() => onSkip(-1)}>
            <SkipBack className="h-4 w-4" aria-hidden />
          </IconButton>
          <button
            type="button"
            onClick={onToggle}
            aria-label={playing ? "Pause (space)" : "Play (space)"}
            title={playing ? "Pause (space)" : "Play (space)"}
            className="bg-honey grid h-9 w-9 place-items-center rounded-full text-[#1c1400] transition hover:brightness-105"
          >
            {playing ? (
              <Pause className="h-4 w-4" aria-hidden />
            ) : (
              <Play className="h-4 w-4 translate-x-px" aria-hidden />
            )}
          </button>
          <IconButton label="Next day (right arrow)" onClick={() => onSkip(1)}>
            <SkipForward className="h-4 w-4" aria-hidden />
          </IconButton>
          <span className="bg-line mx-1 hidden h-5 w-px sm:block" aria-hidden />
          <div className="hidden items-center gap-0.5 sm:flex" role="group" aria-label="Speed">
            {SPEEDS.map((value) => (
              <IconButton
                key={value}
                label={`${value}× speed (key ${SPEEDS.indexOf(value) + 1})`}
                onClick={() => onSpeed(value)}
                active={speed === value}
              >
                <span className="tabular px-0.5">{value}×</span>
              </IconButton>
            ))}
          </div>
        </>
      )}
      <span className="hidden sm:contents">
        <IconButton label="Keyboard shortcuts (?)" onClick={onHelp}>
          <Keyboard className="h-4 w-4" aria-hidden />
        </IconButton>
      </span>
      <span className="hidden sm:contents">
        <IconButton
          label={fullscreen ? "Leave full screen (F)" : "Full screen (F)"}
          onClick={onFullscreen}
        >
          {fullscreen ? (
            <Minimize2 className="h-4 w-4" aria-hidden />
          ) : (
            <Maximize2 className="h-4 w-4" aria-hidden />
          )}
        </IconButton>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------------------
// Tally
// ---------------------------------------------------------------------------------------

function Figure({
  label,
  cents,
  swatch,
  hint,
}: {
  label: string;
  cents: number;
  /** A status colour for the mark beside the label; the number itself stays in ink. */
  swatch?: string;
  hint?: string;
}) {
  return (
    <div className="bg-surface px-3.5 py-3" title={hint}>
      <dt className="text-muted flex items-center gap-1.5 text-[11px]">
        {swatch ? (
          <span className="h-2 w-2 rounded-full" style={{ background: swatch }} aria-hidden />
        ) : null}
        {label}
      </dt>
      <dd className="tabular text-ink mt-0.5 text-lg font-semibold">
        <AnimatedNumber value={cents} format={moneyWhole} />
      </dd>
    </div>
  );
}

export function Tally({ world }: { world: World }) {
  const stats = world.stats;
  return (
    <section
      className="border-line bg-surface overflow-hidden rounded-2xl border"
      aria-label="The week so far"
    >
      <div className="px-4 pt-4 pb-3">
        <div className="text-ink-2 text-xs font-medium">Saved by twelve shops this week</div>
        <div className="tabular text-ink mt-0.5 text-5xl font-semibold tracking-tight">
          <AnimatedNumber value={stats?.saved_cents ?? 0} format={moneyWhole} />
        </div>
        <p className="text-ink-2 mt-1 text-xs">
          {stats && stats.saved_cents > 0 && stats.negotiation_saved_cents > 0
            ? `${money(stats.negotiation_saved_cents)} of it won by the agents negotiating`
            : stats && stats.negotiation_saved_cents > 0
              ? `${money(stats.negotiation_saved_cents)} won by negotiating; it counts once the orders are placed`
              : "against what each shop would pay buying alone"}
        </p>
      </div>
      <dl className="bg-line border-line grid grid-cols-2 gap-px border-t">
        <Figure
          label="Held on PayPal"
          cents={world.heldCents}
          swatch="var(--honey)"
          hint="Reserved on the shops' PayPal, not taken"
        />
        <Figure
          label="Charged"
          cents={world.chargedCents}
          swatch="var(--good)"
          hint="Captured for what was actually delivered"
        />
        <Figure
          label="Paid out"
          cents={world.paidOutCents}
          swatch="var(--ink)"
          hint="To suppliers and neighbours, by PayPal Payouts"
        />
        <Figure
          label="Released or refunded"
          cents={world.releasedCents + world.refundedCents}
          swatch="var(--warning)"
          hint="Holds given back for what didn't arrive, plus refunds"
        />
      </dl>
      <div className="border-line text-ink-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t px-4 py-2.5 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <Leaf className="text-good-ink h-3.5 w-3.5" aria-hidden />
          {kg(stats?.food_saved_grams ?? 0)} of food not wasted
        </span>
        <span
          className="tabular"
          title={
            world.realCalls > 0
              ? "Calls to the real PayPal sandbox; the rest went to the simulator"
              : "No sandbox keys are set, so every call went to the simulator, which follows the same rules"
          }
        >
          {world.paypalCalls} PayPal calls
          {world.paypalCalls === 0
            ? ""
            : world.realCalls > 0
              ? `, ${world.realCalls} real`
              : ", all simulated"}
        </span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------------------
// Negotiation
// ---------------------------------------------------------------------------------------

/**
 * One lane per supplier on a shared price scale (cheaper to the left): a faint dot for
 * each earlier quote and a solid one for the latest. Dots, not bars, because the quotes
 * differ by a few percent, which a zero-based bar would hide.
 */
export function NegotiationPanel({
  negotiation,
  names,
}: {
  negotiation: Negotiation;
  names: Record<string, string>;
}) {
  const all = negotiation.trails.flatMap((trail) => trail.landed);
  const low = Math.min(...all);
  const high = Math.max(...all);
  const span = Math.max(1, high - low);
  const position = (value: number) => 6 + ((value - low) / span) * 88;
  const best = all.length ? low : null;
  const trails = [...negotiation.trails].sort((a, b) => a.supplier.localeCompare(b.supplier));
  const label = CATEGORY_LABEL[negotiation.category] ?? negotiation.category;

  return (
    <section
      className="border-line bg-surface rounded-2xl border p-4"
      aria-label={`Negotiation for ${label}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-ink text-sm font-semibold">
          {negotiation.winner ? "Deal agreed" : "Negotiating"}: {label.toLowerCase()}
        </h2>
        <span className="text-muted text-xs">
          {negotiation.round ? `round ${negotiation.round} of 3` : "asking for quotes"}
        </span>
      </div>
      <ul className="mt-3 space-y-2.5">
        {trails.map((trail) => {
          const latest = trail.landed[trail.landed.length - 1];
          const won = negotiation.winner === trail.supplier;
          return (
            <li key={trail.supplier}>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-ink inline-flex min-w-0 items-center gap-1.5 font-medium">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: slotColor(trail.supplier) }}
                    aria-hidden
                  />
                  <span className="truncate">{names[trail.supplier] ?? trail.supplier}</span>
                  {won ? (
                    <span className="bg-good-soft text-good-ink inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-semibold">
                      <Trophy className="h-3 w-3" aria-hidden /> won
                    </span>
                  ) : null}
                </span>
                <span className="tabular text-ink-2 shrink-0">
                  {latest ? money(latest) : trail.declined ? "can't supply" : "..."}
                </span>
              </div>
              <div className="relative mt-1.5 h-3" aria-hidden>
                <div className="bg-grid absolute inset-x-0 top-1/2 h-px" />
                {trail.landed.map((value, index) => {
                  const last = index === trail.landed.length - 1;
                  return (
                    <motion.span
                      key={index}
                      className="absolute top-1/2 block rounded-full"
                      initial={{
                        left: `${position(trail.landed[index - 1] ?? value)}%`,
                        scale: 0.4,
                      }}
                      animate={{ left: `${position(value)}%`, scale: 1 }}
                      transition={{ duration: 0.5, ease: "easeOut" }}
                      style={{
                        width: last ? 10 : 6,
                        height: last ? 10 : 6,
                        marginLeft: last ? -5 : -3,
                        marginTop: last ? -5 : -3,
                        background: slotColor(trail.supplier),
                        opacity: last ? 1 : 0.35,
                        boxShadow: last ? "0 0 0 2px var(--surface)" : undefined,
                      }}
                    />
                  );
                })}
              </div>
            </li>
          );
        })}
        {trails.length === 0 ? (
          <li className="text-muted text-xs">Three supplier agents have been asked for a price.</li>
        ) : null}
      </ul>
      <div className="text-muted mt-2 flex justify-between text-[10px]">
        <span>cheaper</span>
        <span className="tabular">{best ? `best so far ${money(best)}` : ""}</span>
        <span>dearer</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------------------
// Money ticker and agent chatter
// ---------------------------------------------------------------------------------------

const MONEY_WORD: Record<string, { word: string; swatch: string }> = {
  hold_placed: { word: "Held", swatch: "var(--honey)" },
  hold_reauthorized: { word: "Hold renewed", swatch: "var(--honey)" },
  hold_voided: { word: "Released", swatch: "var(--warning)" },
  hold_failed: { word: "Hold failed", swatch: "var(--critical)" },
  captured: { word: "Charged", swatch: "var(--good)" },
  refunded: { word: "Refunded", swatch: "var(--warning)" },
  supplier_paid: { word: "Paid", swatch: "var(--ink)" },
  swap_completed: { word: "Neighbour paid", swatch: "var(--ink)" },
  flash_deal_bought: { word: "Flash deal", swatch: "var(--good)" },
};

export function MoneyTicker({
  events,
  names,
  rows: limit = 6,
}: {
  events: PayPalEvent[];
  names: Record<string, string>;
  rows?: number;
}) {
  const rows = events.filter((event) => MONEY_WORD[event.kind]).slice(0, limit);
  return (
    <section
      className="border-line bg-surface rounded-2xl border p-4"
      aria-label="PayPal, as it happens"
    >
      <h2 className="text-ink text-sm font-semibold">PayPal, as it happens</h2>
      {rows.length === 0 ? (
        <p className="text-muted mt-2 text-xs">
          Nothing has moved yet. Money is only held once a deal is agreed.
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {rows.map((event) => {
            const { word, swatch } = MONEY_WORD[event.kind];
            // A neighbour sale is named after who was paid; everything else after the shop
            // or supplier it happened to.
            const who =
              event.kind === "swap_completed"
                ? event.seller
                : (event.shop ?? event.supplier ?? event.buyer);
            return (
              <motion.li
                key={event.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.25 }}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <span className="text-ink-2 inline-flex min-w-0 items-center gap-1.5">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: swatch }}
                    aria-hidden
                  />
                  <span className="text-ink shrink-0 font-medium">
                    {word}
                    {event.kind === "captured" && event.partial ? " (short delivery)" : ""}
                  </span>
                  <span className="truncate">{who ? (names[who] ?? who) : ""}</span>
                </span>
                <span className="tabular text-ink shrink-0 font-medium">
                  {money(event.amount_cents)}
                </span>
              </motion.li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function Chatter({
  messages,
  names,
}: {
  messages: AgentMessage[];
  names: Record<string, string>;
}) {
  // Agents talking to each other; an owner's chat is theirs.
  const rows = messages
    .filter((m) => !m.from.startsWith("owner:") && !m.to.startsWith("owner:") && m.text)
    .slice(-5);
  return (
    <section
      // On a short window there is no room for it under the tally and the money.
      className="border-line bg-surface hidden min-h-0 flex-1 flex-col rounded-2xl border p-4 [@media(min-height:840px)]:flex"
      aria-label="What the agents are saying"
    >
      <h2 className="text-ink text-sm font-semibold">What the agents are saying</h2>
      {rows.length === 0 ? (
        <p className="text-muted mt-2 text-xs">Quiet for now.</p>
      ) : (
        <ul className="mt-2 flex min-h-0 flex-1 flex-col justify-end gap-2 overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_2.25rem)]">
          {rows.map((message) => (
            <motion.li
              key={message.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
              className="text-xs"
            >
              <div className="text-muted flex items-center gap-1">
                <span className="text-ink-2 truncate font-medium">
                  {agentName(message.from, names)}
                </span>
                <ArrowRight className="h-3 w-3 shrink-0" aria-hidden />
                <span className="truncate">{agentName(message.to, names)}</span>
              </div>
              <p className="text-ink mt-0.5 line-clamp-2 leading-snug">{message.text}</p>
            </motion.li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------------
// Title card and finale
// ---------------------------------------------------------------------------------------

const DAY_NAME: Record<string, string> = {
  Mon: "Monday",
  Tue: "Tuesday",
  Wed: "Wednesday",
  Thu: "Thursday",
  Fri: "Friday",
  Sat: "Saturday",
  Sun: "Sunday",
};

/** The day's title, shown over the map for a moment when a step begins. */
export function TitleCard({ step }: { step: Step }) {
  const [day, what] = splitTitle(step.title);
  return (
    <motion.div
      key={step.key}
      className="pointer-events-none absolute inset-0 z-10 grid place-items-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      aria-hidden
    >
      <div className="absolute inset-0 bg-[color-mix(in_oklab,var(--page)_72%,transparent)] backdrop-blur-[2px]" />
      <motion.div
        className="relative px-6 text-center"
        initial={{ y: 14, scale: 0.97 }}
        animate={{ y: 0, scale: 1 }}
        exit={{ y: -10 }}
        transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
      >
        <div className="text-honey text-xs font-semibold tracking-[0.3em] uppercase">
          {DAY_NAME[day] ?? day} · {what}
        </div>
        <div className="text-ink mx-auto mt-3 max-w-2xl text-3xl leading-tight font-semibold tracking-tight text-balance sm:text-5xl">
          {step.description}
        </div>
      </motion.div>
    </motion.div>
  );
}

export type FinaleFacts = {
  overchargeCents: number;
  rejectedInvoices: number;
  releasedCents: number;
  swaps: number;
};

export function Finale({
  world,
  facts,
  onReplay,
}: {
  world: World;
  facts: FinaleFacts;
  onReplay: () => void;
}) {
  const stats = world.stats;
  if (!stats) return null;
  const calls = (stats.paypal_calls.REAL ?? 0) + (stats.paypal_calls.SIMULATED ?? 0);
  const lines: { icon: React.ReactNode; title: string; detail: string }[] = [
    {
      icon: <Trophy className="h-4 w-4" aria-hidden />,
      title: `${money(stats.negotiation_saved_cents)} won by negotiating`,
      detail: "Three supplier agents competed over three rounds for one pooled order.",
    },
    {
      icon: <Undo2 className="h-4 w-4" aria-hidden />,
      title: `${money(facts.releasedCents)} given back for a short delivery`,
      detail: "Shops were charged for what arrived, and the rest of each hold was released.",
    },
    ...(facts.rejectedInvoices
      ? [
          {
            icon: <ShieldAlert className="h-4 w-4" aria-hidden />,
            title: `A ${money(facts.overchargeCents)} overcharge caught`,
            detail:
              "The supplier's invoice was checked line by line and rejected before it was paid.",
          },
        ]
      : []),
    {
      icon: <Leaf className="h-4 w-4" aria-hidden />,
      title: `${kg(stats.food_saved_grams)} of food not wasted`,
      detail: `${facts.swaps} neighbour-to-neighbour ${facts.swaps === 1 ? "sale" : "sales"}, paid on the spot.`,
    },
    {
      icon: <BookCheck className="h-4 w-4" aria-hidden />,
      title: stats.books_balanced ? "Every cent accounted for" : "The books need a look",
      detail: `${calls} PayPal calls (${stats.paypal_calls.REAL ? `${stats.paypal_calls.REAL} on the real sandbox` : "all simulated"}), ${moneyWhole(stats.captured_cents)} charged, ${moneyWhole(stats.payouts_cents)} paid out.`,
    },
  ];

  return (
    <motion.div
      className="absolute inset-0 z-20 grid place-items-center overflow-y-auto p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      role="dialog"
      aria-label="The week in review"
    >
      <div className="absolute inset-0 bg-[color-mix(in_oklab,var(--page)_82%,transparent)] backdrop-blur-sm" />
      <motion.div
        className="border-line-strong bg-surface relative w-full max-w-2xl rounded-3xl border p-6 shadow-2xl sm:p-8"
        initial={{ y: 24, scale: 0.97 }}
        animate={{ y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
      >
        <div className="text-honey text-xs font-semibold tracking-[0.25em] uppercase">
          One week in Tiong Bahru
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-1">
          <div className="tabular text-ink text-6xl font-semibold tracking-tight sm:text-7xl">
            <AnimatedNumber value={stats.saved_cents} format={moneyWhole} />
          </div>
          <p className="text-ink-2 pb-2 text-sm">
            saved by {stats.shops} shops
            <br />
            that used to buy alone
          </p>
        </div>
        <ul className="mt-6 grid gap-3 sm:grid-cols-2">
          {lines.map((line, index) => (
            <motion.li
              key={line.title}
              className="flex gap-3"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35 + index * 0.12, duration: 0.3 }}
            >
              <span className="bg-surface-2 text-ink grid h-8 w-8 shrink-0 place-items-center rounded-lg">
                {line.icon}
              </span>
              <span>
                <span className="text-ink block text-sm font-semibold">{line.title}</span>
                <span className="text-ink-2 block text-xs leading-snug">{line.detail}</span>
              </span>
            </motion.li>
          ))}
        </ul>
        <div className="mt-7 flex flex-wrap gap-2">
          <Link
            href="/live"
            className="bg-honey inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-[#1c1400] transition hover:brightness-105"
          >
            Explore the live board <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
          <Link
            href="/money"
            className="border-line-strong text-ink hover:bg-surface-2 inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium transition"
          >
            See where every cent went
          </Link>
          <button
            type="button"
            onClick={onReplay}
            className="text-ink-2 hover:bg-surface-2 hover:text-ink inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition"
          >
            <RotateCcw className="h-4 w-4" aria-hidden /> Watch again
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------------------

const SHORTCUTS: [string[], string][] = [
  [["Space"], "Play or pause"],
  [["←", "→"], "Previous or next day"],
  [["1", "2", "3"], "Speed: 1×, 2×, 4×"],
  [["R"], "Start again"],
  [["F"], "Full screen"],
  [["?"], "Show or hide this list"],
  [["Esc"], "Close"],
];

export function ShortcutList({ onClose }: { onClose: () => void }) {
  return (
    <motion.div
      className="absolute inset-0 z-30 grid place-items-center p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-label="Keyboard shortcuts"
        className="border-line-strong bg-surface w-full max-w-sm rounded-2xl border p-5 shadow-2xl"
      >
        <h2 className="text-ink text-sm font-semibold">Keyboard shortcuts</h2>
        <dl className="mt-3 space-y-2 text-sm">
          {SHORTCUTS.map(([keys, what]) => (
            <div key={what} className="flex items-center justify-between gap-4">
              <dt className="text-ink-2">{what}</dt>
              <dd className="flex shrink-0 gap-1">
                {keys.map((key) => (
                  <kbd
                    key={key}
                    className="border-line-strong bg-surface-2 text-ink min-w-7 rounded-md border px-1.5 py-0.5 text-center font-sans text-xs font-medium"
                  >
                    {key}
                  </kbd>
                ))}
              </dd>
            </div>
          ))}
        </dl>
        <p className="text-muted mt-4 text-xs">
          While the week plays, these buttons fade after a moment so a recording stays clean. Move
          the mouse to bring them back.
        </p>
      </div>
    </motion.div>
  );
}
