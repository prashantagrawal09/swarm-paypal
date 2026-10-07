"use client";

/**
 * One Server-Sent Events connection for the whole app. It keeps the recent agent messages
 * and PayPal events, tells components which shop just had activity (map pulses, swap arcs),
 * and revalidates every SWR query shortly after anything happens so the numbers agree.
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

type LiveState = {
  connected: boolean;
  /** False until the stream has connected once (so the UI can say "connecting", not "offline"). */
  started: boolean;
  messages: AgentMessage[];
  events: PayPalEvent[];
  activity: Record<string, { at: number; kind: string }>;
  arcs: Arc[];
};

const LiveContext = createContext<LiveState>({
  connected: false,
  started: false,
  messages: [],
  events: [],
  activity: {},
  arcs: [],
});

const MAX_MESSAGES = 250;
const MAX_EVENTS = 80;
const REVALIDATE_MS = 1200;
let eventCounter = 0;

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const { mutate } = useSWRConfig();
  const [connected, setConnected] = useState(false);
  const [started, setStarted] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [events, setEvents] = useState<PayPalEvent[]>([]);
  const [activity, setActivity] = useState<LiveState["activity"]>({});
  const [arcs, setArcs] = useState<Arc[]>([]);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      const codes = [message.from, message.to]
        .filter((id) => id.startsWith("shop:") || id.startsWith("owner:"))
        .map((id) => id.split(":")[1]);
      touch(codes, message.type);
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
      } else {
        setEvents((current) => [item, ...current].slice(0, MAX_EVENTS));
        touch([data.shop, data.buyer, data.seller], data.kind);
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
  }, [revalidateSoon, touch]);

  const value = useMemo(
    () => ({ connected, started, messages, events, activity, arcs }),
    [connected, started, messages, events, activity, arcs],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveState {
  return useContext(LiveContext);
}
