"use client";

/** The live board: the week's headline, the neighbourhood map, the deals, and both feeds. */

import {
  BookCheck,
  BookX,
  CircleDollarSign,
  Landmark,
  Leaf,
  MessagesSquare,
  Play,
  Wallet,
} from "lucide-react";
import useSWR from "swr";

import { AgentFeed, PayPalFeed } from "@/components/feeds";
import { GroupOrderCard } from "@/components/group-order-card";
import { NeighbourActivity } from "@/components/neighbour-activity";
import { ShopMap } from "@/components/shop-map";
import { AnimatedNumber, HeroFigure, StatTile } from "@/components/stats";
import { ButtonLink, Card, CardHeader, Empty, StatusPill } from "@/components/ui";
import { WeekStepper } from "@/components/week-stepper";
import type { GroupOrder, Overview, ShopSummary } from "@/lib/api";
import { kg, money, moneyWhole, shortDate } from "@/lib/format";

export function LiveBoard() {
  const { data: overview, error } = useSWR<Overview>("/api/overview");
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const { data: groups } = useSWR<GroupOrder[]>("/api/group-orders");

  if (error && !overview) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6">
        <Empty>
          The Swarm backend isn&apos;t answering. Start it with{" "}
          <code className="font-mono">make backend</code> and this page connects on its own.
        </Empty>
      </div>
    );
  }

  const stats = overview?.stats;
  const calls = stats ? (stats.paypal_calls.REAL ?? 0) + (stats.paypal_calls.SIMULATED ?? 0) : 0;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      {/* Headline */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:items-end">
        <div>
          <div className="text-ink-2 flex items-center gap-2 text-xs font-medium">
            <span>Tiong Bahru</span>
            <span className="text-muted">·</span>
            <span>Week of {overview ? shortDate(`${overview.week}T00:00:00+08:00`) : "..."}</span>
            {overview?.running ? <StatusPill tone="busy">Running</StatusPill> : null}
          </div>
          <div className="mt-3">
            <HeroFigure
              label="Saved by neighbourhood shops this week"
              value={stats?.saved_cents ?? 0}
              format={moneyWhole}
              detail={
                stats ? (
                  <>
                    {money(stats.negotiation_saved_cents)} of it won by the agents negotiating ·{" "}
                    <span className="inline-flex items-center gap-1">
                      <Leaf className="text-good-ink h-3.5 w-3.5" aria-hidden />
                      {kg(stats.food_saved_grams)} of food kept out of the bin
                    </span>
                  </>
                ) : (
                  "Loading..."
                )
              }
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <StatTile
            label="PayPal API calls"
            value={<AnimatedNumber value={calls} format={(v) => v.toLocaleString("en-SG")} />}
            detail={
              stats
                ? `${stats.paypal_calls.REAL ?? 0} real sandbox · ${stats.paypal_calls.SIMULATED ?? 0} simulated`
                : undefined
            }
            accent={<CircleDollarSign className="text-muted h-3.5 w-3.5" aria-hidden />}
          />
          <StatTile
            label="Held right now"
            value={money(stats?.holds_outstanding_cents ?? 0)}
            detail="authorized, not yet charged"
            accent={<Wallet className="text-muted h-3.5 w-3.5" aria-hidden />}
          />
          <StatTile
            label="Charged for deliveries"
            value={money(stats?.captured_cents ?? 0)}
            detail={stats ? `${money(stats.refunds_cents)} refunded` : undefined}
          />
          <StatTile
            label="Paid to suppliers"
            value={money(stats?.payouts_cents ?? 0)}
            detail="by PayPal Payouts"
            accent={<Landmark className="text-muted h-3.5 w-3.5" aria-hidden />}
          />
          <StatTile
            label="Swarm fee"
            value={money(stats?.fees_cents ?? 0)}
            detail="2% of supplier payouts"
          />
          <StatTile
            label="Books"
            value={
              stats ? (
                stats.books_balanced ? (
                  <span className="inline-flex items-center gap-1.5">
                    <BookCheck className="text-good-ink h-4 w-4" aria-hidden /> Balanced
                  </span>
                ) : (
                  <span className="text-critical inline-flex items-center gap-1.5">
                    <BookX className="h-4 w-4" aria-hidden /> Check ledger
                  </span>
                )
              ) : (
                "-"
              )
            }
            detail="double-entry ledger"
          />
        </div>
      </section>

      {/* Week */}
      <Card className="mt-6 px-4 py-5 sm:px-6">
        {overview ? (
          <WeekStepper steps={overview.steps} running={overview.running} />
        ) : (
          <div className="h-16" />
        )}
        {overview && overview.steps.every((s) => s.status !== "done") && !overview.running ? (
          <div className="border-line text-ink-2 mt-4 flex flex-wrap items-center justify-center gap-3 border-t pt-4 text-sm">
            The week hasn&apos;t started.
            <ButtonLink href="/demo" variant="honey">
              <Play className="h-4 w-4" aria-hidden /> Run it from the demo panel
            </ButtonLink>
          </div>
        ) : null}
      </Card>

      {/* Map + feeds */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <Card>
            <CardHeader
              title="The neighbourhood"
              subtitle="Each pin is a shop and its agent. Tap one for its week."
            />
            <div className="px-3 pb-4 sm:px-5">
              {shops ? (
                <ShopMap shops={shops} />
              ) : (
                <div className="bg-surface-2 aspect-[720/440] animate-pulse rounded-xl" />
              )}
            </div>
          </Card>

          <section aria-labelledby="deals">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 id="deals" className="text-ink text-sm font-semibold">
                This week&apos;s group orders
              </h2>
              <span className="text-muted hidden text-xs sm:inline">
                Price per unit falls as the order grows
              </span>
            </div>
            {groups && groups.length ? (
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                {groups.map((group) => (
                  <GroupOrderCard key={group.id} group={group} />
                ))}
              </div>
            ) : (
              <Empty>
                Group orders appear on Tuesday, after the shop agents send in their weekly needs.
              </Empty>
            )}
          </section>

          <NeighbourActivity />
        </div>

        <div className="space-y-6 lg:col-span-5">
          <Card className="flex h-[620px] flex-col">
            <CardHeader
              title="Agents talking"
              subtitle="Shops, suppliers and the coordinator, live"
              icon={MessagesSquare}
            />
            <AgentFeed className="flex-1" />
          </Card>
          <Card className="flex h-[520px] flex-col">
            <CardHeader
              title="PayPal"
              subtitle="Holds, charges, payouts, refunds and invoices as they happen"
              icon={CircleDollarSign}
            />
            <PayPalFeed className="flex-1" />
          </Card>
        </div>
      </div>
    </div>
  );
}
