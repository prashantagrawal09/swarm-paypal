"use client";

/** The two live feeds: what the agents are saying, and what PayPal is doing with money. */

import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  Ban,
  FileCheck2,
  FileText,
  FileX2,
  Hand,
  HandCoins,
  type LucideIcon,
  Repeat2,
  RotateCcw,
  ShieldAlert,
  ScanSearch,
  Sparkles,
  Undo2,
  Zap,
} from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import useSWR from "swr";

import { hasExplanation, useInspect } from "@/components/message-inspector";
import { cx, ModeBadge, Mono } from "@/components/ui";
import { type AgentMessage, fetcher, type PaymentRow } from "@/lib/api";
import { agentKind, agentName, initials, money, slotColor, time } from "@/lib/format";
import { type PayPalEvent, useLive } from "@/lib/live";
import { paymentEvent } from "@/lib/payment-events";
import { useNames } from "@/lib/use-names";

export { useNames } from "@/lib/use-names";

// ---------------------------------------------------------------------------------------
// Agent conversation
// ---------------------------------------------------------------------------------------

const TOPICS = {
  // Agents talking to each other. What an owner and their own agent say is under Owners.
  all: {
    label: "Agents",
    match: (m: AgentMessage) => !m.from.startsWith("owner:") && !m.to.startsWith("owner:"),
  },
  deals: {
    label: "Negotiation",
    match: (m: AgentMessage) =>
      m.conversation_id.startsWith("neg") ||
      [
        "RFQ",
        "QUOTE",
        "COUNTER",
        "FINAL_CALL",
        "FINAL_QUOTE",
        "AWARD",
        "NOT_AWARDED",
        "DECLINE",
        "NO_QUOTES",
        "NO_AWARD",
        "AWARD_SUMMARY",
        "JOIN",
      ].includes(m.type),
  },
  neighbours: {
    label: "Neighbours",
    match: (m: AgentMessage) =>
      /SWAP|SURPLUS|EMERGENCY|FLASH/.test(m.type) ||
      /swap|surplus|emergency|flash/.test(m.conversation_id),
  },
  money: {
    label: "Invoices & claims",
    match: (m: AgentMessage) => /INVOICE|PAID|PAYMENT|CLAIM/.test(m.type),
  },
  owners: {
    label: "Owners",
    match: (m: AgentMessage) => m.from.startsWith("owner:") || m.to.startsWith("owner:"),
  },
} as const;

type Topic = keyof typeof TOPICS;

const TYPE_LABEL: Record<string, string> = {
  RFQ: "Request for quote",
  QUOTE: "Quote",
  COUNTER: "Counter-offer",
  FINAL_CALL: "Final call",
  FINAL_QUOTE: "Final quote",
  AWARD: "Awarded",
  NOT_AWARDED: "Not this time",
  AWARD_SUMMARY: "Award",
  AWARD_NEWS: "Award",
  WEEKLY_NEEDS: "Weekly order",
  INVOICE: "Invoice",
  INVOICE_APPROVED: "Invoice OK",
  INVOICE_REJECTED: "Invoice rejected",
  INVOICE_CANCELLED: "Invoice cancelled",
  PAID: "Paid",
  PAYMENT_RECORDED: "Payment recorded",
  SURPLUS_OFFER: "Surplus",
  EMERGENCY_REQUEST: "Emergency",
  FLASH_DEAL: "Flash deal",
  CLAIM: "Claim",
  CLAIM_DECISION: "Claim decision",
  OWNER_REPLY: "Owner",
};

function Avatar({ id, names }: { id: string; names: Record<string, string> }) {
  const kind = agentKind(id);
  const code = id.split(":")[1] ?? "";
  if (kind === "coordinator" || id.startsWith("claims")) {
    return (
      <span
        className="bg-honey grid h-7 w-7 shrink-0 place-items-center rounded-full text-[#1c1400]"
        aria-hidden
      >
        <Sparkles className="h-3.5 w-3.5" />
      </span>
    );
  }
  if (kind === "supplier") {
    return (
      <span
        className="bg-surface text-ink grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 text-[10px] font-semibold"
        style={{ borderColor: slotColor(code) }}
        aria-hidden
      >
        {initials(names[code] ?? code).toUpperCase()}
      </span>
    );
  }
  if (kind === "owner") {
    return (
      <span
        className="bg-ink text-page grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold"
        aria-hidden
      >
        {initials(names[code] ?? code).toUpperCase()}
      </span>
    );
  }
  return (
    <span
      className="bg-surface-3 text-ink grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold"
      aria-hidden
    >
      {initials(names[code] ?? code).toUpperCase() || "·"}
    </span>
  );
}

export function AgentFeed({
  className,
  initialTopic = "all",
  filter,
  conversations,
  openAt = "newest",
}: {
  className?: string;
  initialTopic?: Topic;
  filter?: (message: AgentMessage) => boolean;
  /**
   * Where the list opens. A live feed follows the newest message; a finished conversation
   * reads better from its first one.
   */
  openAt?: "newest" | "oldest";
  /**
   * Show these conversations in full: their history is loaded from the server, however
   * long ago they happened, and anything new arrives live.
   */
  conversations?: string[];
}) {
  const { messages: live, connected } = useLive();
  const names = useNames();
  const inspect = useInspect();
  const [topic, setTopic] = useState<Topic>(initialTopic);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(openAt === "newest");

  const { data: history } = useSWR<AgentMessage[]>(
    conversations?.length ? ["conversations", ...conversations] : null,
    async ([, ...ids]: string[]) =>
      (
        await Promise.all(
          ids.map((id) =>
            fetcher<AgentMessage[]>(
              `/api/agent-messages?limit=500&conversation_id=${encodeURIComponent(id)}`,
            ),
          ),
        )
      ).flat(),
    { revalidateOnFocus: false },
  );

  const messages = useMemo(() => {
    if (!conversations?.length) return live;
    const wanted = new Set(conversations);
    const byId = new Map<string, AgentMessage>();
    for (const message of history ?? []) byId.set(message.id, message);
    for (const message of live)
      if (wanted.has(message.conversation_id)) byId.set(message.id, message);
    return [...byId.values()].sort((a, b) => a.seq - b.seq);
  }, [conversations, history, live]);

  const shown = useMemo(
    () => messages.filter((m) => TOPICS[topic].match(m) && (!filter || filter(m))).slice(-120),
    [messages, topic, filter],
  );

  // Follow the newest message unless the reader has scrolled up. Our own jumps are flagged
  // so the scroll handler doesn't mistake them for the reader.
  const lastId = shown[shown.length - 1]?.id;
  const programmatic = useRef(false);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !stick.current) return;
    programmatic.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => {
      programmatic.current = false;
    });
  }, [lastId, topic]);

  return (
    <div className={cx("flex min-h-0 flex-col", className)}>
      <div
        className="flex items-center gap-1 overflow-x-auto px-4 pb-2"
        role="tablist"
        aria-label="Filter messages"
      >
        {(Object.keys(TOPICS) as Topic[]).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={topic === key}
            onClick={() => {
              stick.current = openAt === "newest";
              if (openAt === "oldest") scroller.current?.scrollTo({ top: 0 });
              setTopic(key);
            }}
            className={cx(
              "shrink-0 rounded-full px-2.5 py-1 text-xs font-medium transition",
              topic === key ? "bg-ink text-page" : "text-ink-2 hover:bg-surface-2",
            )}
          >
            {TOPICS[key].label}
          </button>
        ))}
      </div>
      <div
        ref={scroller}
        onScroll={(event) => {
          if (programmatic.current) return;
          const el = event.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        }}
        className="feed min-h-0 flex-1 overflow-y-auto px-4 pb-4"
        aria-live="polite"
        aria-relevant="additions"
        // Focusable, so the keyboard can scroll it.
        tabIndex={0}
        role="log"
        aria-label="Agent conversation"
      >
        {shown.length === 0 ? (
          <div className="text-muted grid h-full min-h-40 place-items-center text-center text-sm">
            {connected
              ? "Quiet for now. Start the week from the demo panel."
              : "Connecting to the live stream..."}
          </div>
        ) : (
          <ol className="space-y-3">
            <AnimatePresence initial={false}>
              {shown.map((message) => (
                <motion.li
                  key={message.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, ease: "easeOut" }}
                  className="flex gap-2.5"
                >
                  <Avatar id={message.from} names={names} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-1.5 text-xs">
                      <span className="text-ink font-semibold">
                        {agentName(message.from, names)}
                      </span>
                      <ArrowRight className="text-muted h-3 w-3" aria-label="to" />
                      <span className="text-ink-2">{agentName(message.to, names)}</span>
                      <span className="bg-surface-2 text-ink-2 rounded px-1.5 py-px text-[10px] font-medium tracking-wide uppercase">
                        {TYPE_LABEL[message.type] ??
                          message.type.replaceAll("_", " ").toLowerCase()}
                      </span>
                      <span className="tabular text-muted ml-auto text-[11px]">
                        {time(message.at)}
                      </span>
                    </div>
                    <p className="text-ink-2 mt-0.5 text-sm leading-snug break-words whitespace-pre-line">
                      {message.text}
                    </p>
                    {hasExplanation(message) ? (
                      <button
                        type="button"
                        onClick={() => inspect(message)}
                        className="text-ink-2 hover:text-ink mt-1 inline-flex items-center gap-1 text-[11px] font-medium underline decoration-dotted underline-offset-2"
                      >
                        <ScanSearch className="h-3 w-3" aria-hidden />
                        How was this decided?
                      </button>
                    ) : null}
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ol>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------
// PayPal events
// ---------------------------------------------------------------------------------------

const EVENT_STYLE: Record<
  string,
  { label: string; icon: LucideIcon; tone: string; sign?: 1 | -1 }
> = {
  hold_placed: { label: "Money held", icon: Hand, tone: "text-honey-ink bg-honey-soft" },
  hold_reauthorized: { label: "Hold renewed", icon: RotateCcw, tone: "text-ink-2 bg-surface-2" },
  hold_voided: { label: "Hold released", icon: Undo2, tone: "text-ink-2 bg-surface-2" },
  hold_failed: {
    label: "Hold failed",
    icon: ShieldAlert,
    tone: "text-critical-ink bg-critical-soft",
  },
  captured: { label: "Charged", icon: ArrowDownLeft, tone: "text-good-ink bg-good-soft" },
  capture_failed: {
    label: "Charge failed",
    icon: ShieldAlert,
    tone: "text-critical-ink bg-critical-soft",
  },
  refunded: { label: "Refunded", icon: Undo2, tone: "text-warning-ink bg-warning-soft" },
  supplier_paid: { label: "Supplier paid", icon: ArrowUpRight, tone: "text-real bg-real-soft" },
  swap_completed: { label: "Neighbour swap", icon: Repeat2, tone: "text-honey-ink bg-honey-soft" },
  flash_deal_bought: { label: "Flash deal", icon: Zap, tone: "text-honey-ink bg-honey-soft" },
  swap_charged: {
    label: "Neighbour charged",
    icon: ArrowDownLeft,
    tone: "text-honey-ink bg-honey-soft",
  },
  swap_payout: {
    label: "Paid to neighbour",
    icon: ArrowUpRight,
    tone: "text-honey-ink bg-honey-soft",
  },
  approval_needed: {
    label: "Asked the owner",
    icon: HandCoins,
    tone: "text-warning-ink bg-warning-soft",
  },
  group_order_cancelled: { label: "Order cancelled", icon: Ban, tone: "text-ink-2 bg-surface-2" },
  invoice_sent: { label: "Invoice sent", icon: FileText, tone: "text-ink-2 bg-surface-2" },
  invoice_checked: {
    label: "Invoice checked",
    icon: FileCheck2,
    tone: "text-good-ink bg-good-soft",
  },
  invoice_cancelled: { label: "Invoice cancelled", icon: FileX2, tone: "text-ink-2 bg-surface-2" },
};

export const PAYPAL_KINDS = new Set(Object.keys(EVENT_STYLE));

function eventTitle(event: PayPalEvent, names: Record<string, string>): string {
  const shop = event.shop ? (names[event.shop] ?? event.shop) : "";
  const supplier = event.supplier ? (names[event.supplier] ?? event.supplier) : "";
  switch (event.kind) {
    case "swap_completed":
      return `${names[event.seller ?? ""] ?? event.seller} → ${names[event.buyer ?? ""] ?? event.buyer}`;
    case "supplier_paid":
      return supplier;
    case "flash_deal_bought":
      return `${shop} from ${supplier}`;
    case "invoice_sent":
    case "invoice_cancelled":
    case "invoice_checked":
      return `${String(event.invoice_number ?? "")} · ${supplier}`;
    default:
      return shop || supplier;
  }
}

function eventDetail(event: PayPalEvent): string | null {
  if (event.kind === "captured" && event.partial && event.hold_cents) {
    return `only what arrived (held ${money(event.hold_cents)})`;
  }
  if (event.kind === "invoice_checked") {
    return event.approved
      ? "matches the agreed prices"
      : `overcharge ${money(Number(event.overcharge_cents ?? 0))} caught`;
  }
  if (event.kind === "supplier_paid" && Number(event.withheld_cents ?? 0) > 0) {
    return `${money(Number(event.withheld_cents))} withheld for an open claim`;
  }
  if (event.reason && typeof event.reason === "string") return event.reason;
  if (event.category && event.category !== "SWAP") return String(event.category).toLowerCase();
  return null;
}

export function PayPalFeed({ className, limit = 40 }: { className?: string; limit?: number }) {
  const { events } = useLive();
  const names = useNames();
  const { data: history } = useSWR<PaymentRow[]>("/api/payments?limit=60");
  const live = events.filter((e) => PAYPAL_KINDS.has(e.kind));
  const seen = new Set(
    live.flatMap((e) => [e.paypal_id, e.capture_paypal_id, e.payout_paypal_id].filter(Boolean)),
  );
  const earlier = (history ?? [])
    .map(paymentEvent)
    .filter((e): e is PayPalEvent => e !== null && !(e.paypal_id && seen.has(e.paypal_id)));
  const shown = [...live, ...earlier].slice(0, limit);

  return (
    <div
      className={cx("feed min-h-0 overflow-y-auto px-4 pb-4", className)}
      aria-live="polite"
      tabIndex={0}
      role="log"
      aria-label="PayPal activity"
    >
      {shown.length === 0 ? (
        <div className="text-muted grid h-full min-h-40 place-items-center text-center text-sm">
          Holds, charges, payouts and invoices appear here as they happen.
        </div>
      ) : (
        <ol className="space-y-1">
          <AnimatePresence initial={false}>
            {shown.map((event) => {
              const style = EVENT_STYLE[event.kind];
              const Icon = style.icon;
              const amount = event.amount_cents ?? null;
              const id =
                event.paypal_id ?? event.capture_paypal_id ?? event.payout_paypal_id ?? null;
              const detail = eventDetail(event);
              return (
                <motion.li
                  key={event.id}
                  layout="position"
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25 }}
                  className="hover:bg-surface-2 flex items-start gap-2.5 rounded-xl px-2 py-2"
                >
                  <span
                    className={cx(
                      "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg",
                      style.tone,
                    )}
                    aria-hidden
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-ink text-sm font-medium">{style.label}</span>
                      {event.mode ? <ModeBadge mode={event.mode} compact /> : null}
                      {amount !== null ? (
                        <span className="tabular text-ink ml-auto text-sm font-semibold">
                          {money(amount)}
                        </span>
                      ) : null}
                    </div>
                    <div className="text-ink-2 flex items-center gap-2 text-xs">
                      <span className="truncate">{eventTitle(event, names)}</span>
                      <span className="tabular text-muted ml-auto shrink-0">{time(event.at)}</span>
                    </div>
                    {detail || id ? (
                      <div className="text-muted mt-0.5 flex items-center gap-2 text-[11px]">
                        {detail ? <span className="truncate">{detail}</span> : null}
                        {id ? (
                          <Mono className="text-muted ml-auto shrink-0">{shortId(id)}</Mono>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
    </div>
  );
}

export function shortId(id: string): string {
  return id.length > 16 ? `${id.slice(0, 6)}…${id.slice(-6)}` : id;
}
