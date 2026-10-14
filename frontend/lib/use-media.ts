"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a media query matches, kept up to date. Before the page is in a browser (the
 * server render, and the first render after it) it answers `fallback`.
 */
export function useMedia(query: string, fallback = false): boolean {
  return useSyncExternalStore(
    (changed) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", changed);
      return () => media.removeEventListener("change", changed);
    },
    () => window.matchMedia(query).matches,
    () => fallback,
  );
}
