"use client";

/**
 * A shop's weekly statement: one page an owner can print or save as a PDF for their books.
 * What was bought with the street, order by order, adding up to what PayPal charged; the
 * PayPal references; what was sold to or borrowed from neighbours; and how the saving adds
 * up.
 */

import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { Button, Logo, Missing, ModeBadge } from "@/components/ui";
import {
  ApiError,
  type DemoState,
  type PaymentRow,
  type ShopDetail,
  type ShopOrderLine,
  type SwapRow,
} from "@/lib/api";
import { CATEGORY_LABEL, dayTime, kg, money, shortDate } from "@/lib/format";
import { statement } from "@/lib/statement";

const PAYMENT_WORD: Record<string, string> = {
  AUTHORIZATION: "Hold placed",
  REAUTHORIZATION: "Hold renewed",
  CAPTURE: "Charged",
  VOID: "Hold released",
  REFUND: "Refunded",
  PAYOUT: "Paid to you",
  SWAP_PAYMENT: "Paid a neighbour",
};

const th = "text-muted py-1.5 text-left text-[11px] font-medium";
const td = "py-1.5 align-top";
const num = "tabular text-right";

export function ShopStatement({ code }: { code: string }) {
  const { data: shop, error } = useSWR<ShopDetail>(`/api/shops/${code}`);
  const { data: lines } = useSWR<ShopOrderLine[]>(`/api/shops/${code}/orders`);
  const { data: payments } = useSWR<PaymentRow[]>(`/api/shops/${code}/payments`);
  const { data: swaps } = useSWR<SwapRow[]>(`/api/shops/${code}/swaps`);
  const { data: state } = useSWR<DemoState>("/api/demo/state");

  if (error instanceof ApiError && error.status === 404) {
    return (
      <Missing
        title={<>There&apos;s no shop called &ldquo;{code}&rdquo;</>}
        href="/shops"
        action="See all shops"
      >
        Twelve shops on the street are part of Swarm. This isn&apos;t one of them.
      </Missing>
    );
  }
  if (!shop || !lines || !payments || !swaps) {
    return <div className="mx-auto h-96 w-full max-w-3xl px-4 py-10" aria-busy="true" />;
  }

  const week = shop.report.week;
  const totals = statement(lines, week);
  const report = shop.report;
  const paid = payments
    .filter((payment) => payment.status === "COMPLETED")
    .sort((a, b) => a.at.localeCompare(b.at));
  const done = swaps.filter((swap) => swap.status === "COMPLETED" && swap.role);

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:py-8 print:max-w-none print:p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link
          href={`/shop/${code}`}
          className="text-ink-2 hover:text-ink inline-flex items-center gap-1 text-xs"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> {shop.name}
        </Link>
        <Button variant="primary" onClick={() => window.print()}>
          <Printer className="h-4 w-4" aria-hidden /> Print or save as PDF
        </Button>
      </div>

      <article className="border-line bg-surface mt-4 rounded-2xl border p-6 text-sm shadow-[var(--shadow)] sm:p-9 print:mt-0 print:rounded-none print:border-0 print:p-0 print:shadow-none">
        {/* Letterhead */}
        <header className="border-line flex flex-wrap items-start justify-between gap-4 border-b pb-5">
          <div>
            <div className="text-ink flex items-center gap-2 font-semibold">
              <Logo className="h-6 w-6" /> Swarm
            </div>
            <h1 className="text-ink mt-4 text-2xl font-semibold tracking-tight">
              Weekly statement
            </h1>
            <p className="text-ink-2 mt-1">
              Week of {shortDate(`${week}T00:00:00+08:00`)} {week.slice(0, 4)}
            </p>
          </div>
          <div className="text-ink-2 text-right text-xs leading-relaxed">
            <div className="text-ink text-sm font-semibold">{shop.name}</div>
            <div>{shop.owner}</div>
            <div className="max-w-[16rem]">{shop.address}</div>
            <div className="mt-1.5 flex justify-end">
              <ModeBadge mode={shop.mode} />
            </div>
          </div>
        </header>

        {/* The week in four numbers */}
        <dl className="border-line grid grid-cols-2 gap-x-6 gap-y-4 border-b py-5 sm:grid-cols-4">
          {[
            ["Saved this week", money(report.total_saved_cents)],
            ["Charged by PayPal", money(totals.chargedCents)],
            ["Released back", money(totals.releasedCents)],
            ["Refunded", money(totals.refundedCents)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-muted text-[11px]">{label}</dt>
              <dd className="tabular text-ink mt-0.5 text-lg font-semibold">{value}</dd>
            </div>
          ))}
        </dl>

        {/* Orders */}
        <section className="pt-6">
          <h2 className="text-ink text-sm font-semibold">Bought together with the street</h2>
          {totals.orders.length === 0 ? (
            <p className="text-ink-2 mt-2 text-xs">
              No orders yet this week. The agent proposes the week&apos;s order on Monday.
            </p>
          ) : (
            totals.orders.map((order) => (
              <div key={order.id} className="mt-4 break-inside-avoid">
                <div className="text-ink-2 flex flex-wrap items-baseline justify-between gap-2 text-xs">
                  <span className="text-ink font-medium">
                    {CATEGORY_LABEL[order.category] ?? order.category}
                  </span>
                  <span>{order.supplier ?? "Supplier not chosen yet"}</span>
                </div>
                {/* On a phone, each line stacks; the table needs more room than there is. */}
                <ul className="border-line mt-1 border-t text-xs sm:hidden">
                  {order.lines.map((line) => {
                    const short =
                      line.qty_delivered !== null && line.qty_delivered < line.qty_requested;
                    return (
                      <li key={line.id} className="border-line border-b py-1.5">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-ink">
                            {line.item}
                            <span className="text-muted"> · {line.brand}</span>
                          </span>
                          <span className="tabular text-ink shrink-0 font-medium">
                            {money(line.line_total_cents)}
                          </span>
                        </div>
                        <div className="text-ink-2 mt-0.5">
                          {line.qty_delivered === null
                            ? `${line.qty_requested} ${line.unit} ordered`
                            : short
                              ? `${line.qty_delivered} of ${line.qty_requested} ${line.unit} arrived`
                              : `${line.qty_delivered} ${line.unit}`}
                          , {money(line.unit_price_cents)} each (
                          {money(line.alone_unit_price_cents)} alone)
                        </div>
                      </li>
                    );
                  })}
                  <li className="border-line flex items-baseline justify-between gap-3 border-b py-1.5">
                    <span className="text-ink-2">Your share of one delivery</span>
                    <span className="tabular text-ink">{money(order.deliveryCents)}</span>
                  </li>
                  <li className="flex items-baseline justify-between gap-3 py-1.5">
                    <span className="text-ink-2">
                      {order.charged
                        ? order.releasedCents > 0
                          ? `PayPal held ${money(order.heldCents)}, charged this and released ${money(order.releasedCents)}`
                          : `PayPal held ${money(order.heldCents)} and charged it`
                        : `PayPal is holding ${money(order.heldCents)}; nothing is charged until delivery`}
                    </span>
                    <span className="tabular text-ink shrink-0 font-semibold">
                      {order.charged ? money(order.chargedCents) : "not yet"}
                    </span>
                  </li>
                </ul>
                {/* Fixed columns, so every order's table lines up with the others. */}
                <table className="mt-1 hidden w-full table-fixed border-collapse text-xs sm:table">
                  <colgroup>
                    <col />
                    <col className="w-[13%]" />
                    <col className="w-[17%]" />
                    <col className="w-[11%]" />
                    <col className="w-[11%]" />
                    <col className="w-[13%]" />
                  </colgroup>
                  <thead>
                    <tr className="border-line border-b">
                      <th scope="col" className={th}>
                        Item
                      </th>
                      <th scope="col" className={`${th} text-right`}>
                        Ordered
                      </th>
                      <th scope="col" className={`${th} text-right`}>
                        Arrived
                      </th>
                      <th scope="col" className={`${th} text-right`}>
                        Alone
                      </th>
                      <th scope="col" className={`${th} text-right`}>
                        Swarm
                      </th>
                      <th scope="col" className={`${th} text-right`}>
                        Total
                      </th>
                    </tr>
                  </thead>
                  <tbody className="text-ink">
                    {order.lines.map((line) => {
                      const short =
                        line.qty_delivered !== null && line.qty_delivered < line.qty_requested;
                      return (
                        <tr key={line.id} className="border-line border-b">
                          <td className={td}>
                            {line.item}
                            <span className="text-muted"> · {line.brand}</span>
                          </td>
                          <td className={`${td} ${num}`}>
                            {line.qty_requested} {line.unit}
                          </td>
                          <td className={`${td} ${num}`}>
                            {line.qty_delivered === null ? (
                              <span className="text-muted">not yet</span>
                            ) : (
                              <>
                                {line.qty_delivered} {line.unit}
                                {short ? <span className="text-ink-2"> (short)</span> : null}
                              </>
                            )}
                          </td>
                          <td className={`${td} ${num} text-ink-2`}>
                            {money(line.alone_unit_price_cents)}
                          </td>
                          <td className={`${td} ${num}`}>{money(line.unit_price_cents)}</td>
                          <td className={`${td} ${num} font-medium`}>
                            {money(line.line_total_cents)}
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="border-line border-b">
                      <td className={`${td} text-ink-2`} colSpan={5}>
                        Your share of one delivery
                      </td>
                      <td className={`${td} ${num}`}>{money(order.deliveryCents)}</td>
                    </tr>
                  </tbody>
                  <tfoot>
                    <tr>
                      <td className={`${td} text-ink-2`} colSpan={5}>
                        {order.charged
                          ? order.releasedCents > 0
                            ? `PayPal held ${money(order.heldCents)}, charged this and released ${money(order.releasedCents)}`
                            : `PayPal held ${money(order.heldCents)} and charged it`
                          : `PayPal is holding ${money(order.heldCents)}; nothing is charged until delivery`}
                      </td>
                      <td className={`${td} ${num} text-ink font-semibold`}>
                        {order.charged ? money(order.chargedCents) : "not yet"}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ))
          )}
        </section>

        {/* Neighbours */}
        {done.length ? (
          <section className="break-inside-avoid pt-7">
            <h2 className="text-ink text-sm font-semibold">With the neighbours</h2>
            <ul className="mt-2 text-xs">
              {done.map((swap) => {
                const selling = swap.role === "seller";
                const other = (selling ? swap.buyer : swap.seller)?.name ?? "a neighbour";
                return (
                  <li
                    key={swap.id}
                    className="border-line flex items-baseline justify-between gap-4 border-b py-1.5"
                  >
                    <span className="text-ink">
                      {selling ? "Sold" : swap.kind === "EMERGENCY" ? "Borrowed" : "Bought"}{" "}
                      {swap.qty} {swap.unit} {swap.product_name} {selling ? "to" : "from"} {other}
                      <span className="text-muted"> · {dayTime(swap.at)}</span>
                    </span>
                    <span className="tabular text-ink font-medium">
                      {selling ? "+" : "-"}
                      {money(swap.price_cents)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {/* PayPal references */}
        {paid.length ? (
          <section className="break-inside-avoid pt-7">
            <h2 className="text-ink text-sm font-semibold">PayPal references</h2>
            <table className="mt-1 w-full border-collapse text-xs">
              <thead>
                <tr className="border-line border-b">
                  <th scope="col" className={th}>
                    When
                  </th>
                  <th scope="col" className={th}>
                    What
                  </th>
                  <th scope="col" className={th}>
                    PayPal ID
                  </th>
                  <th scope="col" className={`${th} text-right`}>
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody className="text-ink">
                {paid.map((payment) => (
                  <tr key={payment.id} className="border-line border-b">
                    <td className={`${td} tabular text-ink-2`}>{dayTime(payment.at)}</td>
                    <td className={td}>{PAYMENT_WORD[payment.kind] ?? payment.kind}</td>
                    <td className={`${td} text-ink-2 font-mono text-[11px] break-all`}>
                      {payment.paypal_id ?? "-"}
                    </td>
                    <td className={`${td} ${num}`}>{money(payment.amount_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        {/* How the saving adds up */}
        <section className="break-inside-avoid pt-7">
          <h2 className="text-ink text-sm font-semibold">How the saving adds up</h2>
          <dl className="mt-2 text-xs">
            {report.groups.map((group) => (
              <div
                key={group.category}
                className="border-line flex items-baseline justify-between gap-4 border-b py-1.5"
              >
                <dt className="text-ink">
                  {CATEGORY_LABEL[group.category] ?? group.category}
                  <span className="text-muted">
                    {" "}
                    · {money(group.paid_cents)} instead of {money(group.alone_cents)} alone
                  </span>
                </dt>
                <dd className="tabular text-ink">{money(group.saved_cents)}</dd>
              </div>
            ))}
            {[
              ["Selling surplus to neighbours", report.swap_income_cents],
              ["Helping a neighbour in a pinch", report.help_income_cents],
              ["Buying a neighbour's surplus at a discount", report.swap_saved_cents],
              ["Supplier flash deals", report.flash_saved_cents],
              ["Refunds for claims", report.refunds_cents],
            ]
              .filter(([, cents]) => Number(cents) > 0)
              .map(([label, cents]) => (
                <div
                  key={String(label)}
                  className="border-line flex items-baseline justify-between gap-4 border-b py-1.5"
                >
                  <dt className="text-ink">{label}</dt>
                  <dd className="tabular text-ink">{money(Number(cents))}</dd>
                </div>
              ))}
            <div className="flex items-baseline justify-between gap-4 py-2">
              <dt className="text-ink font-semibold">Saved this week</dt>
              <dd className="tabular text-ink text-base font-semibold">
                {money(report.total_saved_cents)}
              </dd>
            </div>
          </dl>
          {report.food_saved_grams > 0 ? (
            <p className="text-ink-2 text-xs">
              {kg(report.food_saved_grams)} of food was sold on instead of thrown away.
            </p>
          ) : null}
        </section>

        <footer className="border-line text-muted mt-7 border-t pt-4 text-[11px] leading-relaxed">
          &ldquo;Alone&rdquo; is the supplier&apos;s own price for an order of your size. Every
          amount here comes from Swarm&apos;s ledger, which is checked against PayPal; the IDs above
          are the ones in your PayPal activity
          {shop.mode === "SIMULATED" ? " (simulated in this demo)" : ""}.
          {state ? ` Prepared ${state.local}.` : ""}
        </footer>
      </article>
    </div>
  );
}
