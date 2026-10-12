"use client";

/** The landing page: what Swarm is, with the neighbourhood's live numbers. */

import {
  ArrowRight,
  Play,
  BadgeDollarSign,
  Bot,
  Calculator,
  FileCheck2,
  Hand,
  Handshake,
  Landmark,
  MessagesSquare,
  Repeat2,
  ShieldCheck,
  Store,
  Truck,
  Undo2,
  Vault,
  Webhook,
} from "lucide-react";
import { motion } from "motion/react";
import useSWR from "swr";

import { useNames } from "@/components/feeds";
import { Reveal } from "@/components/reveal";
import { AnimatedNumber } from "@/components/stats";
import { SwarmMap } from "@/components/swarm-map";
import { ButtonLink, Card, cx, Logo } from "@/components/ui";
import type { Overview, ShopSummary, SupplierSummary } from "@/lib/api";
import { agentName, kg, moneyWhole } from "@/lib/format";
import { useLive } from "@/lib/live";

const WEEK = [
  {
    day: "Mon",
    title: "Each shop's agent proposes the week",
    body: 'From sales history and the owner\'s habits. The owner taps OK, or replies "less milk".',
    icon: Store,
  },
  {
    day: "Tue",
    title: "Pooled, then negotiated",
    body: "Twelve small orders become one big one. Three supplier agents quote, counter and give a final price.",
    icon: Handshake,
  },
  {
    day: "Tue",
    title: "Money held, not taken",
    body: "PayPal authorizes each shop's share, inside the owner's weekly limit.",
    icon: Hand,
  },
  {
    day: "Thu",
    title: "Charged for what arrived",
    body: "Short delivery? The capture is smaller, automatically. Damage claims refund in minutes.",
    icon: Truck,
  },
  {
    day: "Fri",
    title: "Invoice checked, supplier paid",
    body: "Every line is checked against the deal. Overcharges are rejected; the rest is paid by Payouts.",
    icon: FileCheck2,
  },
  {
    day: "Sat",
    title: "Neighbours help neighbours",
    body: "Surplus milk is sold down the street before it expires; an emergency tray of eggs is borrowed in minutes.",
    icon: Repeat2,
  },
];

const PAYPAL = [
  {
    icon: Vault,
    title: "Vault",
    body: "One approval saves the owner's PayPal so the agent can act without logins.",
  },
  {
    icon: Hand,
    title: "Orders: authorize",
    body: "Each shop's share is held, never taken up front.",
  },
  {
    icon: BadgeDollarSign,
    title: "Payments: capture",
    body: "Only what was delivered is charged; the rest of the hold is released.",
  },
  {
    icon: Undo2,
    title: "Refunds",
    body: "Claims and swaps refund to the original PayPal payment.",
  },
  {
    icon: FileCheck2,
    title: "Invoicing",
    body: "Suppliers bill through PayPal; Swarm checks and records payment.",
  },
  {
    icon: Landmark,
    title: "Payouts",
    body: "Suppliers and neighbour sellers are paid out, minus a 2% fee.",
  },
  {
    icon: Webhook,
    title: "Webhooks",
    body: "Verified events keep Swarm's books in step with PayPal.",
  },
];

const AGENTS = [
  {
    icon: Store,
    title: "12 shop agents",
    body: "Know their owner's usual week, brand rules and spending limit.",
  },
  {
    icon: Handshake,
    title: "3 supplier agents",
    body: "Each with its own style and a private price floor nobody else sees.",
  },
  {
    icon: MessagesSquare,
    title: "A coordinator",
    body: "Pools orders, runs the negotiation, checks invoices.",
  },
  {
    icon: ShieldCheck,
    title: "A claims agent",
    body: "Looks at the owner's photo and refunds clear cases itself.",
  },
];

export function Landing() {
  const { data } = useSWR<Overview>("/api/overview");
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const { data: suppliers } = useSWR<SupplierSummary[]>("/api/suppliers");
  const { connected, messages } = useLive();
  const names = useNames();
  const stats = data?.stats;
  // Agent-to-agent talk only (owner chats are private to the owner), without the repeats a
  // broadcast produces.
  const recent = messages
    .filter((m) => !m.from.startsWith("owner:") && !m.to.startsWith("owner:"))
    .filter(
      (m, index, all) => all.findIndex((o) => o.from === m.from && o.text === m.text) === index,
    )
    .slice(-10);

  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="honeycomb border-line relative overflow-hidden border-b">
        <div
          className="bg-honey/25 pointer-events-none absolute -top-48 right-[-8%] h-[520px] w-[520px] rounded-full blur-3xl"
          aria-hidden
        />
        <div className="relative mx-auto grid max-w-7xl grid-cols-1 gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:items-center">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          >
            <p className="border-line bg-surface text-ink-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium">
              <Logo className="h-4 w-4" /> Tiong Bahru, Singapore
            </p>
            <h1 className="text-ink mt-5 text-4xl leading-[1.04] font-semibold tracking-tight text-balance sm:text-6xl">
              Small shops buy alone and pay retail.
              <span className="text-ink-2 block">Swarm lets them buy like a chain.</span>
            </h1>
            <p className="text-ink-2 mt-6 max-w-xl text-lg">
              AI agents pool a neighbourhood&apos;s weekly orders, negotiate with suppliers, and
              settle every cent through PayPal. Money is held, never taken, until the delivery
              arrives.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <ButtonLink href="/live?play=1" variant="honey" className="px-5 py-2.5">
                <Play className="h-4 w-4" aria-hidden /> Watch a week run
              </ButtonLink>
              <ButtonLink href="/live" variant="primary" className="px-5 py-2.5">
                Open the live board <ArrowRight className="h-4 w-4" aria-hidden />
              </ButtonLink>
            </div>
            <p className="text-muted mt-4 text-xs">
              Two minutes, start to finish. Nothing to install, no login.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.6, ease: "easeOut", delay: 0.1 }}
          >
            <Card className="overflow-hidden">
              <div className="flex items-start justify-between gap-4 px-5 pt-5">
                <div>
                  <div className="text-ink-2 text-xs font-medium">This week in Tiong Bahru</div>
                  <div className="tabular text-ink mt-1 text-5xl font-semibold tracking-tight">
                    <AnimatedNumber value={stats?.saved_cents ?? 0} format={moneyWhole} />
                  </div>
                  <div className="text-ink-2 text-sm">
                    saved by {stats?.shops ?? 12} independent shops
                  </div>
                </div>
                <span className="border-line text-ink-2 inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs">
                  <span
                    className={cx(
                      "h-2 w-2 rounded-full",
                      connected ? "live-dot bg-good" : "bg-muted",
                    )}
                    aria-hidden
                  />
                  {data?.running ? "Running now" : connected ? "Live" : "Connecting"}
                </span>
              </div>
              <div className="px-2 pt-1">
                {shops ? (
                  <SwarmMap
                    shops={shops}
                    suppliers={suppliers}
                    heldCents={stats?.holds_outstanding_cents ?? 0}
                    interactive={false}
                  />
                ) : (
                  <div className="aspect-[720/500]" />
                )}
              </div>
              <dl className="border-line bg-line grid grid-cols-2 gap-px border-t text-sm sm:grid-cols-4">
                {[
                  {
                    label: "Won by negotiating",
                    value: (
                      <AnimatedNumber
                        value={stats?.negotiation_saved_cents ?? 0}
                        format={moneyWhole}
                      />
                    ),
                  },
                  { label: "Food not wasted", value: kg(stats?.food_saved_grams ?? 0) },
                  {
                    label: "PayPal calls",
                    value: (
                      <AnimatedNumber
                        value={
                          (stats?.paypal_calls.REAL ?? 0) + (stats?.paypal_calls.SIMULATED ?? 0)
                        }
                        format={(v) => v.toLocaleString("en-SG")}
                      />
                    ),
                  },
                  {
                    label: "Books",
                    value: stats ? (stats.books_balanced ? "Balanced" : "Check") : "-",
                  },
                ].map((item) => (
                  <div key={item.label} className="bg-surface px-4 py-3">
                    <dt className="text-muted text-[11px]">{item.label}</dt>
                    <dd className="tabular text-ink mt-0.5 font-semibold">{item.value}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </motion.div>
        </div>

        {/* What the agents are saying, as it happens */}
        {recent.length ? (
          <div
            className="border-line bg-surface/70 relative border-t backdrop-blur"
            aria-label="Latest agent messages"
          >
            <div className="marquee-mask overflow-hidden py-2.5">
              <ul className="marquee text-ink-2 gap-10 text-xs">
                {[...recent, ...recent].map((message, index) => (
                  <li
                    key={`${message.id}-${index}`}
                    className="flex shrink-0 items-center gap-2"
                    aria-hidden={index >= recent.length}
                  >
                    <span className="bg-honey h-1.5 w-1.5 rounded-full" aria-hidden />
                    <span className="text-ink font-medium">{agentName(message.from, names)}</span>
                    <span className="max-w-[46ch] truncate">{message.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}
      </section>

      {/* The week */}
      <section className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <h2 className="text-ink text-2xl font-semibold tracking-tight">One week with Swarm</h2>
        <p className="text-ink-2 mt-2 max-w-2xl">
          The owners spend about a minute on their phones. The agents do the rest.
        </p>
        <ol className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {WEEK.map(({ day, title, body, icon: Icon }, index) => (
            <Reveal as="li" key={title} delay={(index % 3) * 0.08}>
              <Card className="hover:border-line-strong h-full p-5 transition-colors">
                <div className="flex items-center gap-2">
                  <span
                    className="bg-honey-soft text-honey-ink grid h-8 w-8 place-items-center rounded-lg"
                    aria-hidden
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="text-muted text-xs font-semibold tracking-wide uppercase">
                    {day}
                  </span>
                </div>
                <h3 className="text-ink mt-3 font-medium">{title}</h3>
                <p className="text-ink-2 mt-1 text-sm">{body}</p>
              </Card>
            </Reveal>
          ))}
        </ol>
      </section>

      {/* PayPal */}
      <section className="border-line bg-surface border-y">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
          <h2 className="text-ink text-2xl font-semibold tracking-tight">
            Every cent moves through PayPal
          </h2>
          <p className="text-ink-2 mt-2 max-w-2xl">
            Seven PayPal building blocks, each doing the job it was built for. Every call is
            idempotent, recorded, and reconciled against a double-entry ledger.
          </p>
          <ul className="mt-8 grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
            {PAYPAL.map(({ icon: Icon, title, body }, index) => (
              <Reveal as="li" key={title} className="flex gap-3" delay={(index % 4) * 0.06}>
                <Icon className="text-real mt-0.5 h-5 w-5 shrink-0" aria-hidden />
                <div>
                  <h3 className="text-ink text-sm font-semibold">{title}</h3>
                  <p className="text-ink-2 mt-0.5 text-sm">{body}</p>
                </div>
              </Reveal>
            ))}
          </ul>
        </div>
      </section>

      {/* Agents */}
      <section className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] lg:items-start">
          <div>
            <h2 className="text-ink text-2xl font-semibold tracking-tight">
              The agents suggest. The code decides.
            </h2>
            <p className="text-ink-2 mt-3">
              A language model writes the messages and reads the owners&apos; replies. It never sets
              an amount: prices, holds, captures, refunds and payouts are computed by tested code,
              inside limits the owner set. What one agent says to another is treated as untrusted
              data.
            </p>
            <div className="border-line bg-surface text-ink-2 mt-6 flex items-center gap-3 rounded-xl border p-4 text-sm">
              <Calculator className="text-ink h-5 w-5 shrink-0" aria-hidden />
              More than 200 tests cover the money engine, the ledger and full simulated weeks.
            </div>
          </div>
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {AGENTS.map(({ icon: Icon, title, body }, index) => (
              <Reveal as="li" key={title} delay={(index % 2) * 0.08}>
                <Card className="hover:border-line-strong h-full p-5 transition-colors">
                  <Icon className="text-ink h-5 w-5" aria-hidden />
                  <h3 className="text-ink mt-3 font-medium">{title}</h3>
                  <p className="text-ink-2 mt-1 text-sm">{body}</p>
                </Card>
              </Reveal>
            ))}
          </ul>
        </div>
        <div className="border-line bg-surface mt-14 flex flex-col items-center gap-4 rounded-2xl border px-6 py-10 text-center">
          <Bot className="text-honey-ink h-6 w-6" aria-hidden />
          <h2 className="text-ink text-xl font-semibold">See a whole week in two minutes</h2>
          <p className="text-ink-2 max-w-lg text-sm">
            One button runs the whole week on the live board. The demo panel lets you change what
            goes wrong and play any shop owner on their phone.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <ButtonLink href="/live?play=1" variant="honey">
              <Play className="h-4 w-4" aria-hidden /> Watch a week run
            </ButtonLink>
            <ButtonLink href="/demo">Demo panel</ButtonLink>
          </div>
        </div>
      </section>
    </div>
  );
}
