"use client";

/**
 * A quiet replay for the home page: once a week has been recorded, play it on a loop so the
 * first thing a visitor sees is the swarm at work, not a finished map. It stops when the
 * map scrolls out of view, and never starts for people who ask for reduced motion.
 */

import { useReducedMotion } from "motion/react";
import { type RefObject, useEffect, useMemo } from "react";

import { type Frame, isComplete } from "@/lib/replay";
import type { StreamItem } from "@/lib/stream-state";
import { usePlayer } from "@/lib/use-player";
import { useRecording } from "@/lib/use-recording";

const NOTHING: StreamItem[] = [];
/** How long the finished week rests on screen before it starts again. */
const REST_MS = 6000;

export function useHeroReplay(
  enabled: boolean,
  target: RefObject<HTMLElement | null>,
): { active: boolean; frame: Frame } {
  const { items } = useRecording();
  const still = useReducedMotion();
  const complete = useMemo(() => isComplete(items), [items]);
  const active = enabled && complete && !still;
  const { frame, atEnd, restart, play, pause } = usePlayer(active ? items : NOTHING, {
    follow: false,
    autoplay: true,
    speed: 2,
  });

  useEffect(() => {
    if (!active || !atEnd || frame.cursor === 0) return;
    const timer = setTimeout(restart, REST_MS);
    return () => clearTimeout(timer);
  }, [active, atEnd, frame.cursor, restart]);

  useEffect(() => {
    const element = target.current;
    if (!element || !active) return;
    const observer = new IntersectionObserver(
      ([entry]) => (entry.isIntersecting ? play() : pause()),
      { threshold: 0.2 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [active, target, play, pause]);

  return { active, frame };
}
