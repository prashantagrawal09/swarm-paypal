"use client";

/** Light / dark / system theme, stored per browser. */

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";
const KEY = "swarm-theme";

/** Runs before paint (inlined in <head>) so there is no flash of the wrong theme. */
export const THEME_SCRIPT = `(() => {
  try {
    const stored = localStorage.getItem("${KEY}") || "system";
    const dark = stored === "dark" || (stored === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();`;

function apply(theme: Theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

const CHANGED = "swarm-theme-changed";

/** Sets the theme from anywhere (the header toggle, the command palette). */
export function setThemePreference(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* private mode: applies for this page only */
  }
  apply(theme);
  window.dispatchEvent(new CustomEvent<Theme>(CHANGED, { detail: theme }));
}

function readTheme(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme | null) ?? "system";
  } catch {
    return "system";
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    // Sync with what the pre-paint script applied; nothing to render before mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(readTheme());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply(readTheme());
    const onSet = (event: Event) => setTheme((event as CustomEvent<Theme>).detail);
    media.addEventListener("change", onChange);
    window.addEventListener(CHANGED, onSet);
    return () => {
      media.removeEventListener("change", onChange);
      window.removeEventListener(CHANGED, onSet);
    };
  }, []);

  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;

  return (
    <button
      type="button"
      onClick={() => setThemePreference(next[theme])}
      className="text-ink-2 hover:bg-surface-2 hover:text-ink grid h-8 w-8 place-items-center rounded-lg transition"
      aria-label={`Theme: ${theme}. Click to change.`}
      title={`Theme: ${theme}`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
