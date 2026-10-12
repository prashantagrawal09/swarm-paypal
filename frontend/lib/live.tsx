"use client";

/**
 * One Server-Sent Events connection for the whole app. It keeps the recent agent messages
 * and PayPal events, turns each into a flight between two agents for the map, keeps the
 * week's story for the narrator, marks who just had activity (pulses, swap arcs), and
 * revalidates every SWR query shortly after anything happens so the numbers agree.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSWRConfig } from "swr";

import { API_URL, type AgentMessage, fetcher } from "@/lib/api";
import { moneyFlight, nodeOf } from "@/lib/flights";

export type PayPalEvent = {
  id: string;
  kind: string;
  at: string;
  shop?: string;
  supplier?: string;
  buyer?: string;
  seller?: string;
  amount_cents?: number;
  gross_cents?: number;
  paypal_id?: string;
  payout_paypal_id?: string;
  capture_paypal_id?: string;
  mode?: "REAL" | "SIMULATED";
  category?: string;
  partial?: boolean;
  hold_cents?: number;
  reason?: string;
  step?: string;
  title?: string;
  [key: string]: unknown;
};

export type Arc = { id: string; from: string; to: string; kind: string; at: number };

/**
 * Something travelling between two agents on the map. Ends are node tokens: `shop:<code>`,
 * `supplier:<code>`, `hub` (the coordinator and Swarm's PayPal balance), or the broadcasts
 * `shop:*` / `supplier:*`.
 */
export type FlightKind = "message" | "hold" | "charge" | "payout" | "refund";
export type Flight = {
  id: string;
  from: string;
  to: string;
  kind: FlightKind;
  at: number;
  /** Milliseconds to wait before taking off, so a burst fans out instead of overlapping. */
  delay: number;
};

/** One line of the week's story, in arrival order (newest first in `timeline`). */
export type StoryItem = { id: string; /** When this browser saw it (ms). */ seenAt: number } & (
  { kind: "event"; event: PayPalEvent } | { kind: "message"; message: AgentMessage }
);

type LiveState = {
  connected: boolean;
  /** False until the stream has connected once (so the UI can say "connecting", not "offline"). */
  started: boolean;
  messages: AgentMessage[];
  events: PayPalEvent[];
  /** Last activity per shop code, supplier code, or "hub". */
  activity: Record<string, { at: number; kind: string }>;
  arcs: Arc[];
  flights: Flight[];
  timeline: StoryItem[];
  /** The negotiation that was just awarded while this page was open (for the spotlight). */
  lastAward: { conversation: string; at: number } | null;
};

const LiveContext = createContext<LiveState>({
  connected: false,
  started: false,
  messages: [],
  events: [],
  activity: {},
  arcs: [],
  flights: [],
  timeline: [],
  lastAward: null,
});

const MAX_MESSAGES = 250;
const MAX_EVENTS = 80;
const MAX_FLIGHTS = 70;
const MAX_STORY = 40;
const FLIGHT_MS = 2600;
const REVALIDATE_MS = 1200;
let eventCounter = 0;
let flightCounter = 0;

/** Agent messages that move the week's story forward (the narrator shows these). */
const STORY_MESSAGES = new Set(["RFQ", "FINAL_CALL", "AWARD_SUMMARY", "NO_AWARD", "FLASH_DEAL"]);
const STORY_EVENTS = new Set([
  "step_started",
  "captured",
  "refunded",
  "supplier_paid",
  "swap_completed",
  "flash_deal_bought",
  "invoice_checked",
  "approval_needed",
  "hold_failed",
  "week_summary",
]);

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const { mutate } = useSWRConfig();
  const [connected, setConnected] = useState(false);
  const [started, setStarted] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [events, setEvents] = useState<PayPalEvent[]>([]);
  const [activity, setActivity] = useState<LiveState["activity"]>({});
  const [arcs, setArcs] = useState<Arc[]>([]);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [timeline, setTimeline] = useState<StoryItem[]>([]);
  const [lastAward, setLastAward] = useState<LiveState["lastAward"]>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const burst = useRef({ at: 0, index: 0 });

  const launch = useCallback((from: string, to: string, kind: FlightKind) => {
    const now = Date.now();
    // Things that arrive together take off one after another.
    burst.current =
      now - burst.current.at < 150
        ? { at: now, index: burst.current.index + 1 }
        : { at: now, index: 0 };
    const flight: Flight = {
      id: `fl-${++flightCounter}`,
      from,
      to,
      kind,
      at: now,
      delay: Math.min(burst.current.index * 45, 1100),
    };
    setFlights((current) =>
      [...current.filter((f) => now - f.at < FLIGHT_MS), flight].slice(-MAX_FLIGHTS),
    );
  }, []);

  const tell = useCallback((item: StoryItem) => {
    setTimeline((current) => [item, ...current].slice(0, MAX_STORY));
  }, []);

  const revalidateSoon = useCallback(() => {
    if (pending.current) return;
    pending.current = setTimeout(() => {
      pending.current = null;
      void mutate((key) => typeof key === "string" && !key.includes("agent-messages"));
    }, REVALIDATE_MS);
  }, [mutate]);

  const touch = useCallback((codes: (string | undefined)[], kind: string) => {
    const now = Date.now();
    setActivity((current) => {
      const next = { ...current };
      for (const code of codes) if (code) next[code] = { at: now, kind };
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetcher<AgentMessage[]>("/api/agent-messages?tail=true&limit=150")
      .then((initial) => {
        if (!cancelled) setMessages(initial);
      })
      .catch(() => undefined);

    const source = new EventSource(`${API_URL}/api/stream`);
    source.addEventListener("open", () => {
      setConnected(true);
      setStarted(true);
    });
    source.addEventListener("error", () => setConnected(false));
    source.addEventListener("hello", () => setConnected(true));
    source.addEventListener("agent_message", (event) => {
      const message = JSON.parse((event as MessageEvent<string>).data) as AgentMessage;
      setMessages((current) => {
        if (current.some((m) => m.id === message.id)) return current;
        return [...current, message].slice(-MAX_MESSAGES);
      });
      const codes = [message.from, message.to].map((id) => {
        const [kind, code] = id.split(":");
        if (kind === "shop" || kind === "owner" || kind === "supplier") return code;
        return kind === "coordinator" || kind === "claims" ? "hub" : undefined;
      });
      touch(codes, message.type);
      const from = nodeOf(message.from);
      const to = nodeOf(message.to);
      if (from && to && from !== to) launch(from, to, "message");
      if (STORY_MESSAGES.has(message.type)) {
        tell({ id: `st-${message.id}`, seenAt: Date.now(), kind: "message", message });
      }
      if (message.type === "AWARD_SUMMARY") {
        setLastAward({ conversation: message.conversation_id, at: Date.now() });
      }
      revalidateSoon();
    });
    source.addEventListener("paypal", (event) => {
      const data = JSON.parse((event as MessageEvent<string>).data) as PayPalEvent;
      const item = { ...data, id: `ev-${++eventCounter}` };
      if (data.kind === "reset") {
        setMessages([]);
        setEvents([]);
        setActivity({});
        setArcs([]);
        setFlights([]);
        setTimeline([]);
        setLastAward(null);
      } else {
        setEvents((current) => [item, ...current].slice(0, MAX_EVENTS));
        touch([data.shop, data.buyer, data.seller, data.supplier], data.kind);
        const money = moneyFlight(data);
        if (money) {
          touch(["hub"], data.kind);
          launch(...money);
        }
        // Ordinary charges would drown the story; only short deliveries make a line.
        const routine = data.kind === "captured" && !data.partial;
        if (STORY_EVENTS.has(data.kind) && !routine) {
          tell({ id: `st-${item.id}`, seenAt: Date.now(), kind: "event", event: item });
        }
        if (data.kind === "swap_completed" && data.seller && data.buyer) {
          const arc: Arc = {
            id: item.id,
            from: data.seller,
            to: data.buyer,
            kind: data.kind,
            at: Date.now(),
          };
          setArcs((current) => [...current.filter((a) => Date.now() - a.at < 8000), arc]);
        }
      }
      revalidateSoon();
    });
    return () => {
      cancelled = true;
      source.close();
      if (pending.current) clearTimeout(pending.current);
    };
  }, [revalidateSoon, touch, launch, tell]);

  const value = useMemo(
    () => ({
      connected,
      started,
      messages,
      events,
      activity,
      arcs,
      flights,
      timeline,
      lastAward,
    }),
    [connected, started, messages, events, activity, arcs, flights, timeline, lastAward],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveState {
  return useContext(LiveContext);
}
