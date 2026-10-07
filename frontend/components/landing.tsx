"use client";

/** The landing page: what Swarm is, with the neighbourhood's live numbers. */

import {
  ArrowRight,
  BadgeDollarSign,
  Bot,
  Calculator,
  FileCheck2,
  Hand,
  Handshake,
  Landmark,
  Leaf,
  MessagesSquare,
  Repeat2,
  ShieldCheck,
  Store,
  Truck,
  Undo2,
  Vault,
  Webhook,
} from "lucide-react";
import useSWR from "swr";

import { AnimatedNumber } from "@/components/stats";
import { ButtonLink, Card, Logo } from "@/components/ui";
import type { Overview } from "@/lib/api";
import { kg, moneyWhole } from "@/lib/format";

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
  const stats = data?.stats;

  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="honeycomb border-line relative overflow-hidden border-b">
        <div className="mx-auto grid max-w-7xl grid-cols-1 gap-10 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-center">
          <div>
            <p className="border-line bg-surface text-ink-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium">
              <Logo className="h-4 w-4" /> Tiong Bahru, Singapore
            </p>
            <h1 className="text-ink mt-5 text-4xl leading-[1.05] font-semibold tracking-tight sm:text-6xl">
              Small shops buy alone and pay retail.
              <span className="text-ink-2 block">Swarm lets them buy like a chain.</span>
            </h1>
            <p className="text-ink-2 mt-6 max-w-xl text-lg">
              AI agents pool a neighbourhood&apos;s weekly orders, negotiate with suppliers, and
              settle every cent through PayPal. Money is held, never taken, until the delivery
              arrives.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <ButtonLink href="/live" variant="primary" className="px-5 py-2.5">
                Watch the live board <ArrowRight className="h-4 w-4" aria-hidden />
              </ButtonLink>
              <ButtonLink href="/demo" className="px-5 py-2.5">
                Run a week yourself
              </ButtonLink>
            </div>
          </div>
          <Card className="p-6">
            <div className="text-ink-2 text-xs font-medium">This week in Tiong Bahru</div>
            <div className="tabular text-ink mt-2 text-5xl font-semibold tracking-tight">
              <AnimatedNumber value={stats?.saved_cents ?? 0} format={moneyWhole} />
            </div>
            <div className="text-ink-2 text-sm">
              saved by {stats?.shops ?? 12} independent shops
            </div>
            <dl className="border-line mt-6 grid grid-cols-2 gap-4 border-t pt-5 text-sm">
              <div>
                <dt className="text-muted text-xs">Won by negotiating</dt>
                <dd className="tabular text-ink mt-0.5 font-semibold">
                  <AnimatedNumber value={stats?.negotiation_saved_cents ?? 0} format={moneyWhole} />
                </dd>
              </div>
              <div>
                <dt className="text-muted flex items-center gap-1 text-xs">
                  <Leaf className="h-3 w-3" aria-hidden /> Food not wasted
                </dt>
                <dd className="tabular text-ink mt-0.5 font-semibold">
                  {kg(stats?.food_saved_grams ?? 0)}
                </dd>
              </div>
              <div>
                <dt className="text-muted text-xs">PayPal API calls</dt>
                <dd className="tabular text-ink mt-0.5 font-semibold">
                  <AnimatedNumber
                    value={(stats?.paypal_calls.REAL ?? 0) + (stats?.paypal_calls.SIMULATED ?? 0)}
                    format={(v) => v.toLocaleString("en-SG")}
                  />
                </dd>
              </div>
              <div>
                <dt className="text-muted text-xs">Books</dt>
                <dd className="text-ink mt-0.5 font-semibold">
                  {stats ? (stats.books_balanced ? "Balanced" : "Check") : "-"}
                </dd>
              </div>
            </dl>
          </Card>
        </div>
      </section>

      {/* The week */}
      <section className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <h2 className="text-ink text-2xl font-semibold tracking-tight">One week with Swarm</h2>
        <p className="text-ink-2 mt-2 max-w-2xl">
          The owners spend about a minute on their phones. The agents do the rest.
        </p>
        <ol className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {WEEK.map(({ day, title, body, icon: Icon }) => (
            <li key={title}>
              <Card className="h-full p-5">
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
            </li>
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
            {PAYPAL.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex gap-3">
                <Icon className="text-real mt-0.5 h-5 w-5 shrink-0" aria-hidden />
                <div>
                  <h3 className="text-ink text-sm font-semibold">{title}</h3>
                  <p className="text-ink-2 mt-0.5 text-sm">{body}</p>
                </div>
              </li>
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
            {AGENTS.map(({ icon: Icon, title, body }) => (
              <li key={title}>
                <Card className="h-full p-5">
                  <Icon className="text-ink h-5 w-5" aria-hidden />
                  <h3 className="text-ink mt-3 font-medium">{title}</h3>
                  <p className="text-ink-2 mt-1 text-sm">{body}</p>
                </Card>
              </li>
            ))}
          </ul>
        </div>
        <div className="border-line bg-surface mt-14 flex flex-col items-center gap-4 rounded-2xl border px-6 py-10 text-center">
          <Bot className="text-honey-ink h-6 w-6" aria-hidden />
          <h2 className="text-ink text-xl font-semibold">See a whole week in two minutes</h2>
          <p className="text-ink-2 max-w-lg text-sm">
            Open the live board in one window and the demo panel in another, then press &ldquo;Run
            the rest of the week&rdquo;.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <ButtonLink href="/live" variant="primary">
              Live board
            </ButtonLink>
            <ButtonLink href="/demo" variant="honey">
              Demo panel
            </ButtonLink>
          </div>
        </div>
      </section>
    </div>
  );
}
