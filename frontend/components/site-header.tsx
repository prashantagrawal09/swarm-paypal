/** Top navigation shared by every page. */

import Link from "next/link";

import { BackendStatus } from "@/components/backend-status";

const NAV = [
  { href: "/live", label: "Live board" },
  { href: "/demo", label: "Demo panel" },
];

export function SiteHeader() {
  return (
    <header className="border-b border-stone-200 bg-white/80 backdrop-blur dark:border-stone-800 dark:bg-stone-950/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-amber-400 text-sm text-stone-900">
              S
            </span>
            Swarm
          </Link>
          <nav className="hidden gap-6 text-sm text-stone-600 sm:flex dark:text-stone-400">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="hover:text-stone-900 dark:hover:text-stone-100"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <BackendStatus />
      </div>
    </header>
  );
}
