"use client";

/**
 * Drives a recording with a timer: play, pause, speed, jump to a day. In `follow` mode the
 * recording is still being written (the week is running right now), so every item is played
 * the moment it arrives instead of on a schedule.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { chapters, EMPTY_FRAME, type Frame, gapAfter, seek, type Speed, step } from "@/lib/replay";
import type { StreamItem } from "@/lib/stream-state";

/** Below this many milliseconds, two items are shown together rather than a frame apart. */
const SAME_FRAME_MS = 14;
const LEAD_IN_MS = 500;

export type Player = {
  frame: Frame;
  playing: boolean;
  speed: Speed;
  /** True when everything recorded so far has been played. */
  atEnd: boolean;
  toggle: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (speed: Speed) => void;
  /** Jump to an item without motion; playback carries on from there. */
  jump: (index: number) => void;
  /** Jump to the next (+1) or previous (-1) day. */
  skip: (direction: 1 | -1) => void;
  restart: () => void;
  /** Show everything recorded so far without motion (used to join a week already running). */
  catchUp: () => void;
};

export function usePlayer(
  items: StreamItem[],
  {
    follow,
    autoplay,
    speed: startSpeed = 1,
  }: { follow: boolean; autoplay: boolean; speed?: Speed },
): Player {
  const [frame, setFrame] = useState<Frame>(EMPTY_FRAME);
  const [playing, setPlaying] = useState(autoplay);
  const [speed, setSpeed] = useState<Speed>(startSpeed);
  // The timer callback reads the newest items without restarting on every arrival.
  const latest = useRef(items);
  useEffect(() => {
    latest.current = items;
  }, [items]);

  const cursor = frame.cursor;
  const atEnd = cursor >= items.length;

  useEffect(() => {
    if (!playing || cursor >= items.length) return;
    const previous = items[cursor - 1];
    const wait = follow ? 0 : previous ? gapAfter(previous) / speed : LEAD_IN_MS;
    const timer = setTimeout(() => {
      const now = Date.now();
      setFrame((current) => {
        const all = latest.current;
        let next = step(current, all, now);
        // Things that belong to the same instant (an owner's tap and the reply) go together.
        while (
          next.cursor < all.length &&
          (follow || gapAfter(all[next.cursor - 1]) / speed < SAME_FRAME_MS)
        ) {
          next = step(next, all, now);
        }
        return next;
      });
    }, wait);
    return () => clearTimeout(timer);
  }, [playing, cursor, items, speed, follow]);

  const jump = useCallback((index: number) => {
    const now = Date.now();
    setFrame((current) => seek(current, latest.current, index, now));
  }, []);

  const skip = useCallback(
    (direction: 1 | -1) => {
      const marks = chapters(latest.current).map((c) => c.index);
      if (direction === 1) {
        const next = marks.find((index) => index > cursor);
        jump(next ?? latest.current.length);
      } else {
        // Back to the start of this day, or the day before when already at its start.
        const before = marks.filter((index) => index < cursor - 3);
        jump(before.length ? before[before.length - 1] : 0);
      }
    },
    [cursor, jump],
  );

  const restart = useCallback(() => {
    setFrame(EMPTY_FRAME);
    setPlaying(true);
  }, []);

  const catchUp = useCallback(() => jump(Number.MAX_SAFE_INTEGER), [jump]);

  return {
    frame,
    playing,
    speed,
    atEnd,
    toggle: useCallback(() => setPlaying((value) => !value), []),
    play: useCallback(() => setPlaying(true), []),
    pause: useCallback(() => setPlaying(false), []),
    setSpeed,
    jump,
    skip,
    restart,
    catchUp,
  };
}
