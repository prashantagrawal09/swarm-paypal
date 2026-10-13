"use client";

/**
 * One Server-Sent Events connection for the whole app. Everything it receives goes through
 * `ingest` (see stream-state.ts), which keeps the recent agent messages and PayPal events,
 * the flights for the map and the week's story; this file adds the connection itself and
 * revalidates every SWR query shortly after anything happens, so the numbers agree.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { useSWRConfig } from "swr";

import { API_URL, type AgentMessage, fetcher } from "@/lib/api";
import {
  EMPTY_STREAM,
  ingest,
  MAX_MESSAGES,
  type StreamItem,
  type StreamState,
} from "@/lib/stream-state";

export type {
  Arc,
  Flight,
  FlightKind,
  PayPalEvent,
  PayPalEventData,
  StoryItem,
  StreamItem,
} from "@/lib/stream-state";

export type LiveState = Pick<
  StreamState,
  "messages" | "events" | "activity" | "arcs" | "flights" | "timeline" | "lastAward"
> & {
  connected: boolean;
  /** False until the stream has connected once (so the UI can say "connecting", not "offline"). */
  started: boolean;
};

/**
 * Exported so a subtree can be given a different stream to show: the watch page puts a
 * replayed week here, and every component that reads `useLive` plays it back unchanged.
 */
export const LiveContext = createContext<LiveState>({
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

type Listener = (item: StreamItem) => void;
const TapContext = createContext<(listener: Listener) => () => void>(() => () => undefined);

const REVALIDATE_MS = 1200;

type Action =
  { type: "item"; item: StreamItem; now: number } | { type: "seed"; messages: AgentMessage[] };

function reduce(state: StreamState, action: Action): StreamState {
  if (action.type === "item") return ingest(state, action.item, action.now);
  // The recent history, fetched once on load; anything that already arrived live wins.
  const seen = new Set(state.messages.map((m) => m.id));
  const older = action.messages.filter((m) => !seen.has(m.id));
  return { ...state, messages: [...older, ...state.messages].slice(-MAX_MESSAGES) };
}

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const { mutate } = useSWRConfig();
  const [connected, setConnected] = useState(false);
  const [started, setStarted] = useState(false);
  const [stream, dispatch] = useReducer(reduce, EMPTY_STREAM);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listeners = useRef(new Set<Listener>());

  const revalidateSoon = useCallback(() => {
    if (pending.current) return;
    pending.current = setTimeout(() => {
      pending.current = null;
      void mutate((key) => typeof key === "string" && !key.includes("agent-messages"));
    }, REVALIDATE_MS);
  }, [mutate]);

  const tap = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetcher<AgentMessage[]>("/api/agent-messages?tail=true&limit=150")
      .then((messages) => {
        if (!cancelled) dispatch({ type: "seed", messages });
      })
      .catch(() => undefined);

    const source = new EventSource(`${API_URL}/api/stream`);
    source.addEventListener("open", () => {
      setConnected(true);
      setStarted(true);
    });
    source.addEventListener("error", () => setConnected(false));
    source.addEventListener("hello", () => setConnected(true));

    const receive = (name: StreamItem["event"]) => (raw: Event) => {
      const message = raw as MessageEvent<string>;
      const seq = Number(message.lastEventId);
      const item = {
        event: name,
        data: JSON.parse(message.data),
        seq: message.lastEventId && Number.isFinite(seq) ? seq : undefined,
      } as StreamItem;
      dispatch({ type: "item", item, now: Date.now() });
      for (const listener of listeners.current) listener(item);
      revalidateSoon();
    };
    source.addEventListener("agent_message", receive("agent_message"));
    source.addEventListener("paypal", receive("paypal"));

    return () => {
      cancelled = true;
      source.close();
      if (pending.current) clearTimeout(pending.current);
    };
  }, [revalidateSoon]);

  const value = useMemo<LiveState>(
    () => ({
      connected,
      started,
      messages: stream.messages,
      events: stream.events,
      activity: stream.activity,
      arcs: stream.arcs,
      flights: stream.flights,
      timeline: stream.timeline,
      lastAward: stream.lastAward,
    }),
    [connected, started, stream],
  );
  return (
    <TapContext.Provider value={tap}>
      <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
    </TapContext.Provider>
  );
}

export function useLive(): LiveState {
  return useContext(LiveContext);
}

/**
 * Every item the live connection receives, as it arrives (after it has been applied to the
 * shared state). Returns a function that registers a listener and gives back its unsubscribe.
 */
export function useStreamTap(): (listener: Listener) => () => void {
  return useContext(TapContext);
}
