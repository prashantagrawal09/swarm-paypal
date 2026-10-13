"use client";

/** Shops helping shops (surplus swaps, emergency borrows) and suppliers' flash deals. */

import { ArrowRight, Leaf, Siren, Timer, Zap } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { Card, CardHeader, Empty, Status } from "@/components/ui";
import type { FlashDeal, SwapRow } from "@/lib/api";
import { kg, money } from "@/lib/format";

export function NeighbourActivity() {
  const { data: swaps } = useSWR<SwapRow[]>("/api/swaps?limit=8");
  const { data: deals } = useSWR<FlashDeal[]>("/api/flash-deals");
  const openDeals = (deals ?? []).slice(0, 3);
  const nothing = swaps?.length === 0 && openDeals.length === 0;

  return (
    <Card>
      <CardHeader
        title="Neighbours and deals"
        subtitle="Surplus sold before it expires, emergency stock borrowed, supplier flash deals"
      />
      <div className="px-5 pb-5">
        {nothing ? (
          <Empty>
            A supplier flash deal goes out on Wednesday; neighbours swap on Friday and Saturday.
          </Empty>
        ) : (
          <ul className="divide-line divide-y">
            {(swaps ?? []).map((swap) => {
              const emergency = swap.kind === "EMERGENCY";
              const Icon = emergency ? Siren : Leaf;
              return (
                <li key={swap.id} className="flex items-start gap-3 py-2.5">
                  <span
                    className="bg-honey-soft text-honey-ink mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg"
                    aria-hidden
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1 text-sm">
                    <div className="flex flex-wrap items-center gap-x-1.5">
                      <span className="text-ink font-medium">
                        {emergency ? "Emergency borrow" : "Surplus swap"}
                      </span>
                      <Status value={swap.status} />
                      <span className="tabular text-ink ml-auto font-medium">
                        {money(swap.price_cents)}
                      </span>
                    </div>
                    <div className="text-ink-2 flex flex-wrap items-center gap-x-1.5 text-xs">
                      <span>
                        {swap.qty} {swap.unit} {swap.product_name}
                      </span>
                      <span className="text-muted">·</span>
                      {swap.seller ? (
                        <Link href={`/shop/${swap.seller.code}`} className="hover:text-ink">
                          {swap.seller.name}
                        </Link>
                      ) : (
                        <span>a neighbour</span>
                      )}
                      <ArrowRight className="text-muted h-3 w-3" aria-label="to" />
                      {swap.buyer ? (
                        <Link href={`/shop/${swap.buyer.code}`} className="hover:text-ink">
                          {swap.buyer.name}
                        </Link>
                      ) : (
                        <span>open to neighbours</span>
                      )}
                    </div>
                    <div className="text-muted mt-0.5 flex flex-wrap gap-x-3 text-[11px]">
                      {swap.food_saved_grams ? (
                        <span className="inline-flex items-center gap-1">
                          <Leaf className="h-3 w-3" aria-hidden /> {kg(swap.food_saved_grams)} not
                          wasted
                        </span>
                      ) : null}
                      {swap.discount_pct ? <span>{swap.discount_pct}% off</span> : null}
                      {swap.seconds_to_sorted !== null ? (
                        <span className="inline-flex items-center gap-1">
                          <Timer className="h-3 w-3" aria-hidden /> sorted in{" "}
                          {swap.seconds_to_sorted < 1
                            ? "under a second"
                            : swap.seconds_to_sorted < 120
                              ? `${Math.round(swap.seconds_to_sorted)} s`
                              : `${Math.round(swap.seconds_to_sorted / 60)} min`}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </li>
              );
            })}
            {openDeals.map((deal) => (
              <li key={deal.id} className="flex items-start gap-3 py-2.5">
                <span
                  className="bg-honey-soft text-honey-ink mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg"
                  aria-hidden
                >
                  <Zap className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0 flex-1 text-sm">
                  <div className="flex flex-wrap items-center gap-x-1.5">
                    <span className="text-ink font-medium">Flash deal</span>
                    <Status value={deal.status} />
                    <span className="tabular text-ink ml-auto font-medium">
                      {money(deal.price_cents)}
                      <span className="text-muted text-xs font-normal"> / {deal.unit}</span>
                    </span>
                  </div>
                  <div className="text-ink-2 text-xs">
                    {deal.supplier.name}: {deal.item}
                    {deal.discount_pct ? `, ${deal.discount_pct}% off` : ""} · {deal.taken}/
                    {deal.qty} taken by {deal.purchases.length} shop
                    {deal.purchases.length === 1 ? "" : "s"}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
