"use client";

/**
 * Command palette (Cmd/Ctrl+K): jump to any page, shop, supplier or this week's group
 * orders, or switch theme, without leaving the keyboard.
 */

import {
  ArrowRight,
  CornerDownLeft,
  type LucideIcon,
  Monitor,
  Moon,
  Package,
  Search,
  Store,
  Sun,
  Truck,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";

import { cx, Kbd } from "@/components/ui";
import type { GroupOrder, ShopSummary, SupplierSummary } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/format";
import { matches } from "@/lib/search";
import { setThemePreference, type Theme } from "@/lib/theme";

type Command = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  keywords?: string;
  icon: LucideIcon;
  action: { go: string } | { theme: Theme };
};

const PAGES = [
  { href: "/watch", label: "Watch the week", keywords: "replay film play theatre story" },
  { href: "/live", label: "Live board", keywords: "map agents paypal feed week" },
  { href: "/shops", label: "Shops", keywords: "directory" },
  { href: "/suppliers", label: "Suppliers", keywords: "directory" },
  { href: "/money", label: "Money", keywords: "payments ledger flow invoices" },
  { href: "/demo", label: "Demo panel", keywords: "run reset surprises phone" },
  { href: "/", label: "Home", keywords: "landing about" },
];

/** Places inside pages, for searches by what is there rather than where. */
const PLACES = [
  {
    href: "/demo#claims",
    label: "Claims waiting for a person",
    hint: "Demo panel",
    keywords: "claim refund approve reject damaged photo",
  },
  {
    href: "/demo#surprises",
    label: "Surprises this week",
    hint: "Demo panel",
    keywords: "short delivery overcharged invoice flash deal surplus emergency damage claim refund",
  },
  {
    href: "/demo#phone",
    label: "Be the owner",
    hint: "Demo panel",
    keywords: "phone telegram chat owner message photo",
  },
  {
    href: "/money#flow",
    label: "Where the money went",
    hint: "Money",
    keywords: "flow sankey charged suppliers fee refunds neighbours",
  },
  {
    href: "/money#capabilities",
    label: "PayPal, capability by capability",
    hint: "Money",
    keywords: "vault authorize hold capture void reauthorize refund payouts invoicing webhooks api",
  },
  {
    href: "/money#ledger",
    label: "Ledger balances",
    hint: "Money",
    keywords: "double entry books balanced accounts",
  },
  {
    href: "/suppliers#contests",
    label: "How the suppliers competed",
    hint: "Suppliers",
    keywords: "quotes won lost scoreboard negotiation price",
  },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  // Only fetched once the palette has been opened.
  const { data: shops } = useSWR<ShopSummary[]>(open ? "/api/shops" : null);
  const { data: suppliers } = useSWR<SupplierSummary[]>(open ? "/api/suppliers" : null);
  const { data: groups } = useSWR<GroupOrder[]>(open ? "/api/group-orders" : null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActive(0);
    opener.current?.focus();
  }, []);

  const show = useCallback(() => {
    opener.current = document.activeElement as HTMLElement | null;
    setOpen(true);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (open) close();
        else show();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close, show]);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const all: Command[] = [
      ...PAGES.map((page) => ({
        id: `page:${page.href}`,
        group: "Pages",
        label: page.label,
        keywords: page.keywords,
        icon: ArrowRight,
        action: { go: page.href },
      })),
      ...PLACES.map((place) => ({
        id: `place:${place.href}`,
        group: "On a page",
        label: place.label,
        hint: place.hint,
        keywords: place.keywords,
        icon: ArrowRight,
        action: { go: place.href },
      })),
      ...(shops ?? []).map((shop) => ({
        id: `shop:${shop.code}`,
        group: "Shops",
        label: shop.name,
        hint: `${shop.owner} · ${shop.kind}`,
        keywords: shop.code,
        icon: Store,
        action: { go: `/shop/${shop.code}` },
      })),
      ...(suppliers ?? []).map((supplier) => ({
        id: `supplier:${supplier.code}`,
        group: "Suppliers",
        label: supplier.name,
        hint: supplier.tagline,
        keywords: supplier.code,
        icon: Truck,
        action: { go: `/supplier/${supplier.code}` },
      })),
      ...(groups ?? []).map((group) => ({
        id: `order:${group.id}`,
        group: "This week's group orders",
        label: CATEGORY_LABEL[group.category] ?? group.category,
        hint: group.supplier
          ? `${group.supplier.name} · ${group.shops} shops`
          : `${group.shops} shops`,
        keywords: `order ${group.category} ${group.pooled_text}`,
        icon: Package,
        action: { go: `/orders/${group.id}` },
      })),
      ...(
        [
          ["light", "Light theme", Sun],
          ["dark", "Dark theme", Moon],
          ["system", "Match my system theme", Monitor],
        ] as const
      ).map(([value, label, icon]) => ({
        id: `theme:${value}`,
        group: "Appearance",
        label,
        keywords: "theme appearance mode colour color",
        icon,
        action: { theme: value },
      })),
    ];
    return query ? all.filter((c) => matches(query, c.label, c.hint, c.keywords, c.group)) : all;
  }, [shops, suppliers, groups, query]);

  const execute = (command: Command | undefined) => {
    if (!command) return;
    close();
    if ("go" in command.action) router.push(command.action.go);
    else setThemePreference(command.action.theme);
  };

  const selected = Math.min(active, Math.max(0, commands.length - 1));

  useEffect(() => {
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${selected}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((selected + 1) % Math.max(1, commands.length));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((selected - 1 + commands.length) % Math.max(1, commands.length));
    } else if (event.key === "Enter") {
      event.preventDefault();
      execute(commands[selected]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") {
      event.preventDefault(); // one focusable thing in here: the search box
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={show}
        className="border-line bg-surface text-muted hover:text-ink-2 hidden h-8 items-center gap-2 rounded-lg border pr-1.5 pl-2.5 text-xs transition lg:inline-flex"
        aria-label="Search and jump (Command K)"
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
        <span>Jump to...</span>
        <Kbd>⌘K</Kbd>
      </button>
      <button
        type="button"
        onClick={show}
        className="text-ink-2 hover:bg-surface-2 grid h-8 w-8 place-items-center rounded-lg lg:hidden"
        aria-label="Search and jump"
      >
        <Search className="h-4 w-4" />
      </button>

      {/* In a portal: the header's backdrop blur would otherwise clip a fixed overlay. */}
      {typeof document === "undefined"
        ? null
        : createPortal(
            <AnimatePresence>
              {open ? (
                <motion.div
                  className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh] backdrop-blur-sm"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.12 }}
                  onMouseDown={(event) => {
                    if (event.target === event.currentTarget) close();
                  }}
                >
                  <motion.div
                    role="dialog"
                    aria-modal="true"
                    aria-label="Jump to a page, shop or supplier"
                    className="border-line-strong bg-surface w-full max-w-xl overflow-hidden rounded-2xl border shadow-2xl"
                    initial={{ opacity: 0, y: -8, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -8, scale: 0.98 }}
                    transition={{ duration: 0.14, ease: "easeOut" }}
                    onKeyDown={onKeyDown}
                  >
                    <div className="border-line flex items-center gap-3 border-b px-4">
                      <Search className="text-muted h-4 w-4 shrink-0" aria-hidden />
                      <input
                        ref={input}
                        value={query}
                        onChange={(event) => {
                          setQuery(event.target.value);
                          setActive(0);
                        }}
                        placeholder="Search shops, suppliers, pages..."
                        className="text-ink placeholder:text-muted quiet-focus h-12 w-full bg-transparent text-sm outline-none"
                        role="combobox"
                        aria-expanded="true"
                        aria-controls="command-list"
                        aria-activedescendant={commands[selected] ? `cmd-${selected}` : undefined}
                        autoComplete="off"
                        spellCheck={false}
                      />
                      <Kbd>esc</Kbd>
                    </div>
                    <ul
                      ref={list}
                      id="command-list"
                      role="listbox"
                      className="feed max-h-[52vh] overflow-y-auto p-2"
                    >
                      {commands.length === 0 ? (
                        <li className="text-muted px-3 py-8 text-center text-sm">
                          Nothing matches &ldquo;{query}&rdquo;.
                        </li>
                      ) : null}
                      {commands.map((command, index) => {
                        const Icon = command.icon;
                        const heading = index === 0 || commands[index - 1].group !== command.group;
                        return (
                          <li key={command.id} role="presentation">
                            {heading ? (
                              <div className="text-muted px-3 pt-2.5 pb-1 text-[11px] font-medium tracking-wide uppercase">
                                {command.group}
                              </div>
                            ) : null}
                            <div
                              id={`cmd-${index}`}
                              data-index={index}
                              role="option"
                              aria-selected={index === selected}
                              onMouseMove={() => setActive(index)}
                              onClick={() => execute(command)}
                              className={cx(
                                "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm",
                                index === selected ? "bg-surface-2 text-ink" : "text-ink-2",
                              )}
                            >
                              <Icon className="text-muted h-4 w-4 shrink-0" aria-hidden />
                              <span className="text-ink shrink-0 font-medium">{command.label}</span>
                              {command.hint ? (
                                <span className="text-muted min-w-0 truncate text-xs">
                                  {command.hint}
                                </span>
                              ) : null}
                              {index === selected ? (
                                <CornerDownLeft
                                  className="text-muted ml-auto h-3.5 w-3.5 shrink-0"
                                  aria-hidden
                                />
                              ) : null}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </motion.div>
                </motion.div>
              ) : null}
            </AnimatePresence>,
            document.body,
          )}
    </>
  );
}
