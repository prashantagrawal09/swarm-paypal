"use client";

/**
 * The watch page: the week as a film. A dark stage with the map in the middle, the day's
 * title as each step begins, one sentence about what is happening, and the money adding up.
 *
 * It plays the week's recording, so every visitor gets their own showing: nothing is reset
 * and PayPal isn't called again. If the week is running right now it follows it live, and
 * if nobody has run it yet it offers to start it.
 */

import { Radio, Rewind, Sparkles, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { DemoKeyPrompt } from "@/components/demo-key-prompt";
import { useNames } from "@/components/feeds";
import { useInspect } from "@/components/message-inspector";
import { STEP_ICON, TONE } from "@/components/narrator";
import { SwarmMap } from "@/components/swarm-map";
import {
  Chatter,
  Controls,
  DayStrip,
  Finale,
  type FinaleFacts,
  MoneyTicker,
  NegotiationPanel,
  ShortcutList,
  Tally,
  TitleCard,
} from "@/components/theatre-parts";
import { Button, cx, Logo } from "@/components/ui";
import { Hive } from "@/components/wake-screen";
import {
  ApiError,
  type Overview,
  post,
  type ShopSummary,
  type Stats,
  type SupplierSummary,
} from "@/lib/api";
import { dayTime, moneyWhole, shortDate } from "@/lib/format";
import { LiveContext, type LiveState } from "@/lib/live";
import { chapters, isComplete, SPEEDS } from "@/lib/replay";
import { currentCaption } from "@/lib/story";
import { useNow } from "@/lib/use-now";
import { usePlayer } from "@/lib/use-player";
import { useRecording } from "@/lib/use-recording";
import { shopsAt, suppliersAt } from "@/lib/world-state";

/** How long a day's title stays up at normal speed: a little less than the pause it fills. */
const TITLE_CARD_MS = 1700;
const TITLE_CARD_MIN_MS = 800;
/** How long without input before the controls fade while the week plays. */
const IDLE_MS = 2800;
const NO_STATS: Stats = {
  saved_cents: 0,
  negotiation_saved_cents: 0,
  food_saved_grams: 0,
  captured_cents: 0,
  payouts_cents: 0,
  refunds_cents: 0,
  holds_outstanding_cents: 0,
  fees_cents: 0,
  paypal_calls: { REAL: 0, SIMULATED: 0 },
  books_balanced: true,
  shops: 12,
  delivered_lines: 0,
};

export function Theatre() {
  const router = useRouter();
  const params = useSearchParams();
  const { items, week, loaded } = useRecording();
  const { data: overview } = useSWR<Overview>("/api/overview");
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const { data: suppliers } = useSWR<SupplierSummary[]>("/api/suppliers");
  const names = useNames();
  const inspect = useInspect();
  const now = useNow(200);

  const complete = useMemo(() => isComplete(items), [items]);
  const marks = useMemo(() => chapters(items), [items]);
  const running = Boolean(overview?.running);
  // The week is being written right now: play each item as it arrives.
  const follow = running && !complete;
  const player = usePlayer(items, { follow, autoplay: true });
  const { frame, atEnd, catchUp, toggle, skip, setSpeed } = player;
  const restartPlayer = player.restart;
  const { stream, world } = frame;

  // Joining a week that is already running: show where it has got to, then follow.
  const joined = useRef(false);
  useEffect(() => {
    if (joined.current || !loaded || !overview) return;
    joined.current = true;
    if (overview.running) catchUp();
  }, [loaded, overview, catchUp]);

  // ---- Starting a week nobody has run yet -------------------------------------------------
  const [starting, setStarting] = useState(false);
  const [needKey, setNeedKey] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const start = useCallback(async () => {
    setStarting(true);
    setProblem(null);
    setNeedKey(false);
    try {
      await post("/api/demo/run-week");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setNeedKey(true);
      else if (!(err instanceof ApiError && err.status === 409)) {
        setProblem(err instanceof Error ? err.message : "That didn't work.");
      }
    } finally {
      setStarting(false);
    }
  }, []);

  const empty = loaded && items.length === 0 && !running;
  // "/watch?play=1" (the home page's button) starts an unrun week without another click.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (!empty || autoStarted.current || !overview?.demo_mode || !params.has("play")) return;
    autoStarted.current = true;
    const timer = setTimeout(() => void start(), 0);
    return () => clearTimeout(timer);
  }, [empty, overview, params, start]);

  // ---- Full screen, keys, and no page scrolling underneath --------------------------------
  const [fullscreen, setFullscreen] = useState(false);
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  }, []);
  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.body.style.overflow = previous;
    };
  }, []);

  const [help, setHelp] = useState(false);
  // The week waits while the shortcut list is open, and carries on when it closes.
  const pausedForHelp = useRef(false);
  const { playing, play, pause } = player;
  const showHelp = useCallback(
    (open: boolean) => {
      if (open && playing) {
        pausedForHelp.current = true;
        pause();
      } else if (!open && pausedForHelp.current) {
        pausedForHelp.current = false;
        play();
      }
      setHelp(open);
    },
    [playing, play, pause],
  );

  const [finaleClosed, setFinaleClosed] = useState(false);
  const restart = useCallback(() => {
    setFinaleClosed(false);
    restartPlayer();
  }, [restartPlayer]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      // A panel on top (the inspector) has the keyboard until it closes.
      if (document.querySelector('[aria-modal="true"]')) return;
      const key = event.key.toLowerCase();
      if (key === "?") showHelp(!help);
      else if (key === "escape" && help) showHelp(false);
      else if (key === "f") toggleFullscreen();
      else if (key === "escape" && !document.fullscreenElement) router.push("/live");
      else if (follow) return;
      else if (key === " ") {
        event.preventDefault();
        toggle();
      } else if (key === "arrowright") skip(1);
      else if (key === "arrowleft") skip(-1);
      else if (key === "r") restart();
      else if (["1", "2", "3"].includes(key)) setSpeed(SPEEDS[Number(key) - 1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [follow, help, showHelp, toggle, skip, setSpeed, restart, router, toggleFullscreen]);

  // While the week plays and nobody is touching anything, the controls step back, so a
  // screen recording shows the stage and nothing else. Any movement brings them back.
  const [idle, setIdle] = useState(false);
  const watching = player.playing && !atEnd && items.length > 0;
  useEffect(() => {
    if (!watching) return;
    let timer = setTimeout(() => setIdle(true), IDLE_MS);
    const wake = () => {
      setIdle(false);
      clearTimeout(timer);
      timer = setTimeout(() => setIdle(true), IDLE_MS);
    };
    window.addEventListener("pointermove", wake);
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    return () => {
      clearTimeout(timer);
      setIdle(false);
      window.removeEventListener("pointermove", wake);
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
    };
  }, [watching]);
  const quiet = idle && watching && !help;

  // ---- What the stage shows ----------------------------------------------------------------
  const stageLive = useMemo<LiveState>(
    () => ({
      connected: true,
      started: true,
      messages: stream.messages,
      events: stream.events,
      activity: stream.activity,
      arcs: stream.arcs,
      flights: stream.flights,
      timeline: stream.timeline,
      lastAward: stream.lastAward,
    }),
    [stream],
  );
  const stagedShops = useMemo(() => (shops ? shopsAt(shops, world) : undefined), [shops, world]);
  const stagedSuppliers = useMemo(
    () => (suppliers ? suppliersAt(suppliers, world) : undefined),
    [suppliers, world],
  );

  const steps = useMemo(() => overview?.steps ?? [], [overview]);
  const stageOverview = useMemo<Overview | null>(() => {
    if (!overview) return null;
    let nextSeen = false;
    return {
      ...overview,
      running: player.playing && !atEnd,
      stats: world.stats ?? NO_STATS,
      steps: overview.steps.map((step) => {
        if (world.steps[step.key] === "done") return { ...step, status: "done" as const };
        if (nextSeen) return { ...step, status: "pending" as const };
        nextSeen = true;
        return { ...step, status: "next" as const };
      }),
    };
  }, [overview, world, player.playing, atEnd]);

  const { caption, id: captionId } = useMemo(
    () =>
      stageOverview
        ? currentCaption(stream.timeline, names, stageOverview)
        : { caption: { title: "", tone: "neutral" as const }, id: "none" },
    [stream.timeline, names, stageOverview],
  );
  const tone = TONE[caption.tone];
  const CaptionIcon = tone.icon ?? (caption.step ? STEP_ICON[caption.step] : undefined) ?? Sparkles;

  // The day's title, for a moment after its step begins (or after jumping to it).
  const begun = stream.timeline.find(
    (line) => line.kind === "event" && line.event.kind === "step_started",
  );
  const card =
    begun &&
    begun.kind === "event" &&
    now - begun.seenAt < Math.max(TITLE_CARD_MIN_MS, TITLE_CARD_MS / player.speed)
      ? steps.find((step) => step.key === begun.event.step)
      : undefined;

  const negotiation =
    world.negotiations.find((n) => n.conversation === world.activeNegotiation) ??
    (world.step === "negotiation" ? world.negotiations[world.negotiations.length - 1] : undefined);

  const facts = useMemo<FinaleFacts>(() => {
    let overchargeCents = 0;
    let rejectedInvoices = 0;
    let swaps = 0;
    for (const item of items) {
      if (item.event !== "paypal") continue;
      if (item.data.kind === "invoice_checked" && item.data.approved === false) {
        rejectedInvoices += 1;
        overchargeCents += Number(item.data.overcharge_cents ?? 0);
      }
      if (item.data.kind === "swap_completed") swaps += 1;
    }
    return { overchargeCents, rejectedInvoices, swaps, releasedCents: world.releasedCents };
  }, [items, world.releasedCents]);

  const ready = loaded && overview && stagedShops;
  const showFinale = complete && atEnd && items.length > 0 && !finaleClosed;
  const pausedPartWay = !complete && !running && atEnd && items.length > 0;
  const progress = items.length ? frame.cursor / items.length : 0;

  return (
    <div className="dark">
      <div
        className={cx(
          "theatre bg-page text-ink fixed inset-0 z-[45] flex flex-col overflow-hidden [--chrome:19rem] lg:![--chrome:16.5rem] [@media(min-height:760px)]:[--chrome:28rem]",
          quiet && "cursor-none",
        )}
      >
        <div className="theatre-glow" aria-hidden />

        {/* Top bar */}
        <header className="border-line relative z-10 flex min-h-14 flex-wrap items-center gap-x-4 gap-y-1 border-b px-3 py-1.5 sm:px-5">
          <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Swarm home">
            <Logo className="h-6 w-6" />
            <span className="text-ink hidden text-sm font-semibold sm:inline">Swarm</span>
          </Link>
          <span
            className={cx(
              "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide uppercase",
              follow ? "border-critical text-critical-ink" : "border-line-strong text-ink-2",
            )}
          >
            {follow ? (
              <>
                <Radio className="h-3 w-3" aria-hidden /> Live
              </>
            ) : empty || !loaded ? (
              "Ready"
            ) : (
              <>
                <Rewind className="h-3 w-3" aria-hidden /> Replay
              </>
            )}
          </span>
          <span className="text-muted hidden text-xs 2xl:inline">
            Tiong Bahru · week of{" "}
            {week || overview ? shortDate(`${week ?? overview?.week}T00:00:00+08:00`) : "..."}
          </span>

          <div className="order-last w-full min-w-0 lg:order-none lg:w-auto lg:flex-1 lg:px-2">
            <DayStrip
              steps={steps}
              progress={world.steps}
              onPick={(step) => {
                const mark = marks.find((m) => m.step === step);
                if (mark && !follow) {
                  setFinaleClosed(true);
                  player.jump(mark.index);
                  player.play();
                }
              }}
            />
          </div>

          <div
            className={cx(
              "ml-auto flex shrink-0 items-center gap-1 transition-opacity duration-500",
              // The buttons step back while the week plays; the days stay, so a recording
              // still shows where in the week it is. Focus brings the buttons back.
              quiet && "opacity-0 focus-within:opacity-100",
            )}
          >
            <Controls
              playing={player.playing && !atEnd}
              speed={player.speed}
              live={follow || empty || !loaded}
              fullscreen={fullscreen}
              onToggle={atEnd && complete ? restart : player.toggle}
              onSpeed={player.setSpeed}
              onSkip={(direction) => {
                setFinaleClosed(direction === -1 ? true : finaleClosed);
                player.skip(direction);
              }}
              onRestart={restart}
              onFullscreen={toggleFullscreen}
              onHelp={() => showHelp(!help)}
            />
            <Link
              href="/live"
              aria-label="Close and open the live board (Esc)"
              title="Close (Esc)"
              className="text-ink-2 hover:bg-surface-2 hover:text-ink grid h-9 w-9 place-items-center rounded-lg transition"
            >
              <X className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </header>

        {/* Stage */}
        <div className="relative z-10 grid min-h-0 flex-1 grid-cols-1 gap-4 p-3 sm:p-5 lg:grid-cols-[minmax(0,1fr)_21rem]">
          <div className="relative flex min-h-0 flex-col">
            {!ready ? (
              <div className="grid flex-1 place-items-center">
                <div className="text-center">
                  <Hive />
                  <p className="text-ink-2 mt-4 text-sm">Loading the week...</p>
                </div>
              </div>
            ) : (
              <LiveContext.Provider value={stageLive}>
                <div className="text-ink-2 tabular flex items-center justify-between text-xs">
                  <span>{world.at ? dayTime(world.at) : overview.local}</span>
                  <span className="lg:hidden">
                    <span className="text-ink font-semibold">
                      {moneyWhole(world.stats?.saved_cents ?? 0)}
                    </span>{" "}
                    saved · {moneyWhole(world.heldCents)} held · {moneyWhole(world.chargedCents)}{" "}
                    charged
                  </span>
                </div>
                <div className="relative grid min-h-0 flex-1 place-items-center">
                  <div style={{ width: "min(100%, calc((100dvh - var(--chrome)) * 1.44))" }}>
                    <SwarmMap
                      shops={stagedShops}
                      suppliers={stagedSuppliers}
                      heldCents={world.heldCents}
                      interactive={false}
                      legend
                    />
                  </div>
                  <AnimatePresence>{card ? <TitleCard step={card} /> : null}</AnimatePresence>
                  {empty ? (
                    <div className="absolute inset-0 z-10 grid place-items-center">
                      <div className="absolute inset-0 bg-[color-mix(in_oklab,var(--page)_78%,transparent)]" />
                      <div className="border-line-strong bg-surface relative w-full max-w-md rounded-3xl border p-6 text-center shadow-2xl">
                        <h1 className="text-ink text-xl font-semibold tracking-tight">
                          This week hasn&apos;t been run yet
                        </h1>
                        <p className="text-ink-2 mt-2 text-sm text-balance">
                          {overview.demo_mode
                            ? "Start it and watch twelve shops buy together, from Monday's forecasts to Sunday's savings report. It takes about a minute."
                            : "This server runs the week on its real schedule. Come back once Monday's forecasts have gone out."}
                        </p>
                        {overview.demo_mode ? (
                          <Button
                            variant="honey"
                            className="mt-5"
                            busy={starting}
                            onClick={() => void start()}
                          >
                            Run the week
                          </Button>
                        ) : null}
                        {needKey ? (
                          <DemoKeyPrompt className="mt-4 text-left" onSaved={() => void start()} />
                        ) : null}
                        {problem ? (
                          <p className="text-critical-ink mt-3 text-xs">{problem}</p>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </div>
                {/* On a tall phone there is room under the map for the money as it moves. */}
                <div className="mt-3 hidden lg:!hidden [@media(min-height:760px)]:block">
                  <MoneyTicker events={stream.events} names={names} rows={3} />
                </div>
              </LiveContext.Provider>
            )}
            <AnimatePresence>
              {showFinale ? <Finale world={world} facts={facts} onReplay={restart} /> : null}
            </AnimatePresence>
            <AnimatePresence>
              {help ? <ShortcutList onClose={() => showHelp(false)} /> : null}
            </AnimatePresence>
          </div>

          <aside className="hidden min-h-0 flex-col gap-3 lg:flex">
            <Tally world={world} />
            {negotiation ? (
              <NegotiationPanel negotiation={negotiation} names={names} />
            ) : (
              <MoneyTicker events={stream.events} names={names} />
            )}
            <Chatter
              messages={stream.messages}
              names={names}
              onInspect={(message) => {
                // The week waits while you read how a decision was made, then carries on.
                const wasPlaying = playing;
                pause();
                inspect(message, { dark: true, onClose: wasPlaying ? play : undefined });
              }}
            />
          </aside>
        </div>

        {/* Lower third: what is happening, in one sentence */}
        <footer className="border-line relative z-10 border-t bg-[color-mix(in_oklab,var(--surface)_70%,transparent)] backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-start gap-3.5 px-4 py-3 sm:px-6 sm:py-4">
            <span
              className={cx(
                "grid h-10 w-10 shrink-0 place-items-center rounded-2xl transition-colors duration-500 sm:h-12 sm:w-12",
                tone.chip,
              )}
              aria-hidden
            >
              <CaptionIcon className="h-5 w-5" />
            </span>
            <div className="min-h-[4.5rem] min-w-0 flex-1" aria-live="polite">
              {pausedPartWay ? (
                <>
                  <p className="text-ink text-lg leading-snug font-semibold sm:text-2xl">
                    The week is paused here.
                  </p>
                  <p className="text-ink-2 mt-0.5 text-sm">
                    <Link href="/live" className="underline underline-offset-2">
                      Carry it on from the live board
                    </Link>
                    , and this page will follow.
                  </p>
                </>
              ) : (
                <motion.div
                  key={captionId}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.22, ease: "easeOut" }}
                >
                  <p className="text-ink text-lg leading-snug font-semibold text-balance sm:text-2xl">
                    {empty
                      ? "Monday morning. Twelve shops, three suppliers, one week."
                      : caption.title}
                  </p>
                  {caption.detail && !empty ? (
                    <p className="text-ink-2 mt-0.5 line-clamp-2 text-sm">{caption.detail}</p>
                  ) : null}
                </motion.div>
              )}
            </div>
          </div>
          {follow ? null : (
            <div className="bg-surface-2 absolute inset-x-0 top-0 h-0.5" aria-hidden>
              <div
                className="bg-honey h-full transition-[width] duration-200 ease-linear"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          )}
        </footer>
      </div>
    </div>
  );
}
