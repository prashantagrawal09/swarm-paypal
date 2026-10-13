"use client";

/**
 * The recorded stream of this week, kept up to date while the week is still being written.
 * Once the recording contains the end of the week it is frozen: a visitor's replay is their
 * own copy, and someone else resetting the demo doesn't pull it out from under them.
 */

import { useCallback, useEffect, useState } from "react";

import { fetcher } from "@/lib/api";
import { useStreamTap } from "@/lib/live";
import { isComplete } from "@/lib/replay";
import type { StreamItem } from "@/lib/stream-state";

type Timeline = { week: string; last_seq: number; events: StreamItem[] };

export type Recording = {
  items: StreamItem[];
  /** The Monday of the recorded week (ISO date), once known. */
  week: string | null;
  /** False until the first load has finished (or failed). */
  loaded: boolean;
  /** Throw the local copy away and load the current week again. */
  reload: () => void;
};

export function useRecording(): Recording {
  const tap = useStreamTap();
  const [items, setItems] = useState<StreamItem[]>([]);
  const [week, setWeek] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    // This load's own bookkeeping (a new one starts on reload).
    const local = { lastSeq: 0, pulling: false, again: false, frozen: false, ready: false };
    let cancelled = false;

    const append = (timeline: Timeline) => {
      const fresh = timeline.events.filter((item) => (item.seq ?? 0) > local.lastSeq);
      local.lastSeq = Math.max(local.lastSeq, timeline.last_seq);
      setWeek(timeline.week);
      if (!fresh.length) return;
      setItems((current) => {
        const next = [...current, ...fresh];
        local.frozen = isComplete(next);
        return next;
      });
    };

    // Ask the server for everything recorded since the last item we have. One request at
    // a time; anything that arrives meanwhile triggers one more afterwards.
    const pull = async () => {
      if (local.pulling) {
        local.again = true;
        return;
      }
      local.pulling = true;
      try {
        do {
          local.again = false;
          const timeline = await fetcher<Timeline>(`/api/timeline?after=${local.lastSeq}`);
          if (cancelled) return;
          append(timeline);
        } while (local.again);
      } catch {
        /* the next item to arrive will try again */
      } finally {
        local.pulling = false;
      }
    };

    const stop = tap((item) => {
      if (local.frozen) return;
      if (item.event === "paypal" && item.data.kind === "reset") {
        local.lastSeq = 0;
        setItems([]);
        return;
      }
      if (item.seq === undefined || item.seq <= local.lastSeq) return;
      if (local.ready && !local.pulling && item.seq === local.lastSeq + 1) {
        local.lastSeq = item.seq;
        setItems((current) => {
          const next = [...current, item];
          local.frozen = isComplete(next);
          return next;
        });
      } else {
        void pull(); // a gap, or still loading: let the server fill it in, in order
      }
    });

    void pull().finally(() => {
      if (cancelled) return;
      local.ready = true;
      setLoaded(true);
    });

    return () => {
      cancelled = true;
      stop();
    };
  }, [tap, generation]);

  const reload = useCallback(() => {
    setItems([]);
    setLoaded(false);
    setGeneration((value) => value + 1);
  }, []);

  return { items, week, loaded, reload };
}
