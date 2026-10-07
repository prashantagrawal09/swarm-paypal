"use client";

/** Top navigation: pages, the Swarm Clock, the live connection and the theme. */

import { Clock3, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { cx, Logo } from "@/components/ui";
import type { DemoState } from "@/lib/api";
import { useLive } from "@/lib/live";
import { ThemeToggle } from "@/lib/theme";

const NAV = [
  { href: "/live", label: "Live board" },
  { href: "/shops", label: "Shops" },
  { href: "/suppliers", label: "Suppliers" },
  { href: "/money", label: "Money" },
  { href: "/demo", label: "Demo panel" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const { connected, started } = useLive();
  const liveWord = connected ? "Live" : started ? "Reconnecting" : "Connecting";
  const { data: state } = useSWR<DemoState>("/api/demo/state");
  const [open, setOpen] = useState(false);

  const active = (href: string) =>
    pathname === href || (href !== "/" && pathname.startsWith(href.replace(/s$/, "")));

  return (
    <header className="border-line bg-page/80 sticky top-0 z-40 border-b backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <Link
          href="/"
          className="text-ink flex items-center gap-2 font-semibold tracking-tight"
          onClick={() => setOpen(false)}
        >
          <Logo className="h-7 w-7" />
          Swarm
        </Link>
        <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active(item.href) ? "page" : undefined}
              className={cx(
                "rounded-lg px-3 py-1.5 text-sm transition",
                active(item.href)
                  ? "bg-surface-2 text-ink font-medium"
                  : "text-ink-2 hover:text-ink",
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {state ? (
            <span
              className="border-line bg-surface text-ink-2 hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs sm:inline-flex"
              title="The Swarm Clock: demo time in Singapore"
            >
              <Clock3 className="text-muted h-3.5 w-3.5" aria-hidden />
              <span className="tabular text-ink font-medium">{state.local}</span>
              {state.running ? <span className="text-honey-ink">· running</span> : null}
            </span>
          ) : null}
          <span
            className="text-ink-2 inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs"
            title={connected ? "Receiving live updates" : "Reconnecting to the live stream"}
          >
            <span
              className={cx("h-2 w-2 rounded-full", connected ? "live-dot bg-good" : "bg-muted")}
              aria-hidden
            />
            <span className="hidden sm:inline">{liveWord}</span>
          </span>
          <ThemeToggle />
          <button
            className="text-ink-2 hover:bg-surface-2 grid h-8 w-8 place-items-center rounded-lg md:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label="Menu"
          >
            {open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </div>
      {open ? (
        <nav className="border-line border-t px-4 py-2 md:hidden" aria-label="Main">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className={cx(
                "block rounded-lg px-3 py-2 text-sm",
                active(item.href) ? "bg-surface-2 text-ink font-medium" : "text-ink-2",
              )}
            >
              {item.label}
            </Link>
          ))}
          {state ? (
            <div className="tabular text-muted px-3 py-2 text-xs">Swarm Clock: {state.local}</div>
          ) : null}
        </nav>
      ) : null}
    </header>
  );
}
