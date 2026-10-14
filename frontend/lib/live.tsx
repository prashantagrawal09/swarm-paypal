"use client";

/**
 * One Server-Sent Events connection for the whole app. Everything it receives goes through
 * `ingest` (see stream-state.ts), which keeps the recent agent messages and PayPal events,
 * the flights for the map and the week's story; this file adds the connection itself and
 * revalidates every SWR query shortly after anything happens, so the numbers agree.
 *
 * A tab nobody is looking at lets go of its connection and catches up when it is shown
 * again. Over plain HTTP a browser allows six connections to one server across all its
 * tabs, so six open tabs each holding a stream would leave none for anything else.
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
  /** False until the recent conversation has been fetched (or failed to be). */
  seeded: boolean;
};

/**
 * Exported so a subtree can be given a different stream to show: the watch page puts a
 * replayed week here, and every component that reads `useLive` plays it back unchanged.
 */
export const LiveContext = createContext<LiveState>({
  connected: false,
  started: false,
  seeded: false,
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

/** If the server never says the replay is over, stop treating events as old after this. */
const CATCH_UP_LIMIT_MS = 4000;

type Action =
  | { type: "item"; item: StreamItem; now: number; quiet: boolean }
  | { type: "seed"; messages: AgentMessage[] };

function reduce(state: StreamState, action: Action): StreamState {
  if (action.type === "item") return ingest(state, action.item, action.now, action.quiet);
  // The recent history, fetched on load and again when a hidden tab comes back; anything
  // that already arrived live wins.
  const seen = new Set(state.messages.map((m) => m.id));
  const fetched = action.messages.filter((m) => !seen.has(m.id));
  if (!fetched.length) return state;
  const messages = [...fetched, ...state.messages].sort((a, b) => a.seq - b.seq);
  return { ...state, messages: messages.slice(-MAX_MESSAGES) };
}

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const { mutate } = useSWRConfig();
  const [connected, setConnected] = useState(false);
  const [started, setStarted] = useState(false);
  const [seeded, setSeeded] = useState(false);
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
    let source: EventSource | null = null;
    // The last recorded event this page has seen, so a new connection can ask for the rest.
    let position = 0;
    // Which run of the recording that position belongs to. It changes on a reset (and when
    // the server restarts); a position from another run means nothing.
    let epoch: string | null = null;
    // True while the server replays what was missed: taken in without motion.
    let replaying = false;
    let replayLimit: ReturnType<typeof setTimeout> | undefined;

    const seed = () =>
      fetcher<AgentMessage[]>(`/api/agent-messages?tail=true&limit=${MAX_MESSAGES}`)
        .then((messages) => {
          if (!cancelled) dispatch({ type: "seed", messages });
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setSeeded(true);
        });

    const receive = (name: StreamItem["event"]) => (raw: Event) => {
      const message = raw as MessageEvent<string>;
      const seq = Number(message.lastEventId);
      const known = message.lastEventId !== "" && Number.isFinite(seq);
      if (known) position = Math.max(position, seq);
      const item = {
        event: name,
        data: JSON.parse(message.data),
        seq: known ? seq : undefined,
      } as StreamItem;
      if (item.event === "paypal" && item.data.kind === "reset") {
        position = 0; // the recording starts again from 1
        if (typeof item.data.epoch === "string") epoch = item.data.epoch;
      }
      dispatch({ type: "item", item, now: Date.now(), quiet: replaying });
      for (const listener of listeners.current) listener(item);
      revalidateSoon();
    };

    /** The demo was reset (or the server restarted) while this page wasn't listening. */
    const startOver = (current: string) => {
      epoch = current;
      position = 0;
      disconnect();
      const reset = { event: "paypal", data: { kind: "reset", at: "" } } as StreamItem;
      dispatch({ type: "item", item: reset, now: Date.now(), quiet: true });
      for (const listener of listeners.current) listener(reset);
      connect();
      void seed();
      revalidateSoon();
    };

    const connect = () => {
      if (cancelled || source) return;
      const query = new URLSearchParams();
      if (position) query.set("after", String(position));
      if (position && epoch) query.set("epoch", epoch);
      const next = new EventSource(`${API_URL}/api/stream${position ? `?${query}` : ""}`);
      source = next;
      next.addEventListener("open", () => {
        setConnected(true);
        setStarted(true);
        // Whatever comes before `caught_up` is a replay of what this page missed.
        replaying = true;
        clearTimeout(replayLimit);
        replayLimit = setTimeout(() => (replaying = false), CATCH_UP_LIMIT_MS);
      });
      next.addEventListener("error", () => setConnected(false));
      next.addEventListener("hello", (raw) => {
        setConnected(true);
        const current: unknown = JSON.parse((raw as MessageEvent<string>).data).epoch;
        if (typeof current !== "string") return;
        if (epoch && current !== epoch) startOver(current);
        else epoch = current;
      });
      next.addEventListener("caught_up", () => {
        replaying = false;
        clearTimeout(replayLimit);
      });
      next.addEventListener("agent_message", receive("agent_message"));
      next.addEventListener("paypal", receive("paypal"));
    };

    const disconnect = () => {
      source?.close();
      source = null;
      clearTimeout(replayLimit);
    };

    const hidden = () => document.visibilityState === "hidden";
    const onVisibility = () => {
      if (hidden()) {
        disconnect();
      } else if (!source) {
        connect();
        // Belt and braces for a long absence: the latest conversation, and fresh numbers.
        void seed();
        revalidateSoon();
      }
    };

    void seed();
    if (!hidden()) connect();
    document.addEventListener("visibilitychange", onVisibility);
    // A page kept for the back button is not being looked at either.
    window.addEventListener("pagehide", disconnect);
    window.addEventListener("pageshow", onVisibility);

    return () => {
      cancelled = true;
      disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", disconnect);
      window.removeEventListener("pageshow", onVisibility);
      if (pending.current) clearTimeout(pending.current);
    };
  }, [revalidateSoon]);

  const value = useMemo<LiveState>(
    () => ({
      connected,
      started,
      seeded,
      messages: stream.messages,
      events: stream.events,
      activity: stream.activity,
      arcs: stream.arcs,
      flights: stream.flights,
      timeline: stream.timeline,
      lastAward: stream.lastAward,
    }),
    [connected, started, seeded, stream],
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
