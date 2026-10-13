"use client";

/**
 * Two things to try on the home page, each one idea the product rests on:
 *
 *  1. Buying together moves everyone down the supplier's price list.
 *  2. PayPal holds the money, then charges only for what arrives.
 *
 * Every number is computed by the server with the pricing rules the week itself runs on
 * (GET /api/explain); this file only shows them.
 */

import { ArrowRight, CheckCircle2, Undo2, Wallet } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import useSWR from "swr";

import { HoldBar } from "@/components/charts/hold-bar";
import { OPTION_WORDS } from "@/components/message-inspector";
import { AnimatedNumber } from "@/components/stats";
import { Card, cx } from "@/components/ui";
import type { Explain } from "@/lib/api";
import { initials, money } from "@/lib/format";
import { useWidth } from "@/lib/use-width";

export function Explainers() {
  const { data } = useSWR<Explain>("/api/explain", { revalidateOnFocus: false });
  if (!data) return null;
  return (
    <section className="mx-auto w-full max-w-7xl px-4 pt-16 sm:px-6">
      <h2 className="text-ink text-2xl font-semibold tracking-tight">
        {data.decision ? "Three ideas. Try them." : "Two ideas. Try them."}
      </h2>
      <p className="text-ink-2 mt-2 max-w-2xl">
        Drag the sliders. The numbers come from the same pricing rules that run the week, using the
        street&apos;s usual {data.product.name} order.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Pooling data={data} />
        <ShortDelivery data={data} />
        {data.decision ? <GuardedChoice decision={data.decision} /> : null}
      </div>
    </section>
  );
}

/**
 * Plays a slider once when its card scrolls into view, so the idea shows itself, then
 * leaves it to the visitor. Returns [value, set, ref for the card]; setting it by hand
 * stops the demonstration.
 */
function useDemonstration(
  frames: number[],
  stepMs: number,
): [number, (value: number) => void, React.RefObject<HTMLDivElement | null>] {
  const [value, setValue] = useState(frames[0]);
  const card = useRef<HTMLDivElement>(null);
  const touched = useRef(false);
  const played = useRef(false);

  useEffect(() => {
    const element = card.current;
    if (!element) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || played.current) return;
        played.current = true;
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          setValue(frames[frames.length - 1]);
          return;
        }
        let index = 0;
        const tick = () => {
          if (touched.current) return;
          index += 1;
          setValue(frames[index]);
          if (index < frames.length - 1) timer = setTimeout(tick, stepMs);
        };
        timer = setTimeout(tick, 700);
      },
      { threshold: 0.45 },
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
    // The frames are fixed for the life of the card.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (next: number) => {
    touched.current = true;
    setValue(next);
  };
  return [value, set, card];
}

// ---------------------------------------------------------------------------------------
// 1. Buying together
// ---------------------------------------------------------------------------------------

function Pooling({ data }: { data: Explain }) {
  const { steps, tiers } = data.pooling;
  const [count, setCount, card] = useDemonstration(
    steps.map((step) => step.shops),
    300,
  );
  const sliderId = useId();
  const step = steps[Math.max(0, Math.min(steps.length, count) - 1)];
  const alone = tiers[0].unit_price_cents;
  const unit = data.product.unit;

  return (
    <Card className="p-5 sm:p-6">
      <div ref={card}>
        <h3 className="text-ink text-lg font-semibold">
          Buying together moves you down the price list
        </h3>
        <p className="text-ink-2 mt-1 text-sm">
          {data.supplier.name} sells {data.product.name} cheaper by the hundred litres. No single
          shop on the street buys that much. Twelve do.
        </p>

        <div className="mt-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div>
            <div className="text-ink-2 text-xs font-medium">Price per {unit}</div>
            <div className="tabular text-ink text-4xl font-semibold tracking-tight">
              <AnimatedNumber value={step.unit_price_cents} format={money} />
            </div>
            <div className="text-muted text-xs">
              {step.unit_price_cents < alone
                ? `down from ${money(alone)} alone`
                : "what one shop pays alone"}
            </div>
          </div>
          <dl className="flex gap-6 text-right">
            <div>
              <dt className="text-muted text-[11px]">One order of</dt>
              <dd className="tabular text-ink font-semibold">
                {step.qty} {unit}
              </dd>
            </div>
            <div>
              <dt className="text-muted text-[11px]">Saved each week</dt>
              <dd className="tabular text-ink font-semibold">
                <AnimatedNumber value={step.saved_cents} format={money} />
              </dd>
            </div>
          </dl>
        </div>

        <TierSteps tiers={tiers} qty={step.qty} max={steps[steps.length - 1].qty} unit={unit} />

        <label htmlFor={sliderId} className="text-ink mt-4 block text-sm font-medium">
          Shops buying together: <span className="tabular">{step.shops}</span>
        </label>
        <input
          id={sliderId}
          type="range"
          className="swarm-range mt-2 w-full"
          min={1}
          max={steps.length}
          step={1}
          value={step.shops}
          onChange={(event) => setCount(Number(event.target.value))}
          aria-valuetext={`${step.shops} shops, ${money(step.unit_price_cents)} per ${unit}`}
        />
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="The shops, in the order they join">
          {steps.map((each) => {
            const joined = each.shops <= step.shops;
            return (
              <li key={each.joined.code}>
                <button
                  type="button"
                  onClick={() => setCount(each.shops)}
                  title={`${each.joined.name}: ${each.joined.qty} ${unit} a week`}
                  aria-label={`${each.joined.name}, ${each.joined.qty} ${unit} a week. Set to ${each.shops} shops.`}
                  aria-pressed={joined}
                  className={cx(
                    "grid h-8 w-8 place-items-center rounded-full border text-[10px] font-semibold transition",
                    joined
                      ? "border-honey bg-honey-soft text-honey-ink"
                      : "border-line text-muted hover:border-line-strong",
                  )}
                >
                  {initials(each.joined.name)}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </Card>
  );
}

/**
 * The supplier's price list as a step line, with the pooled order's position on it.
 * One series, so no legend: each step is labelled with its price and where it starts.
 */
function TierSteps({
  tiers,
  qty,
  max,
  unit,
}: {
  tiers: Explain["pooling"]["tiers"];
  qty: number;
  max: number;
  unit: string;
}) {
  const [frame, W] = useWidth<HTMLDivElement>(0);
  const H = 150;
  const PAD = { top: 22, right: 14, bottom: 26, left: 14 };
  const xMax = max * 1.08;
  const prices = tiers.map((tier) => tier.unit_price_cents);
  const high = Math.max(...prices);
  const low = Math.min(...prices);
  const span = Math.max(1, high - low);
  const x = (q: number) => PAD.left + (q / xMax) * (W - PAD.left - PAD.right);
  const y = (cents: number) =>
    PAD.top + (1 - (cents - (low - span * 0.35)) / (span * 1.5)) * (H - PAD.top - PAD.bottom);
  const priceAt = (q: number) =>
    tiers.reduce((price, tier) => (q >= tier.min_qty ? tier.unit_price_cents : price), prices[0]);

  let path = "";
  tiers.forEach((tier, index) => {
    const from = x(index === 0 ? 0 : tier.min_qty);
    const to = x(index + 1 < tiers.length ? tiers[index + 1].min_qty : xMax);
    path += `${index === 0 ? "M" : "L"}${from},${y(tier.unit_price_cents)} L${to},${y(tier.unit_price_cents)} `;
  });
  const price = priceAt(qty);

  return (
    <div ref={frame} className="mt-4">
      {W > 0 ? (
        <svg
          width={W}
          height={H}
          className="block overflow-visible"
          role="img"
          aria-label={`Price per ${unit} by order size: ${tiers
            .map((tier) => `${money(tier.unit_price_cents)} from ${tier.min_qty} ${unit}`)
            .join(", ")}. This order of ${qty} ${unit} pays ${money(price)}.`}
        >
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={H - PAD.bottom}
            y2={H - PAD.bottom}
            stroke="var(--axis)"
            strokeWidth={1}
          />
          {tiers.map((tier, index) => (
            <g key={tier.min_qty}>
              {index > 0 ? (
                <>
                  <line
                    x1={x(tier.min_qty)}
                    x2={x(tier.min_qty)}
                    y1={PAD.top - 6}
                    y2={H - PAD.bottom}
                    stroke="var(--grid)"
                    strokeWidth={1}
                    strokeDasharray="3 4"
                  />
                  <text
                    x={x(tier.min_qty)}
                    y={H - PAD.bottom + 16}
                    textAnchor="middle"
                    className="tabular fill-[var(--muted)] text-[10px]"
                  >
                    {tier.min_qty} {unit}
                  </text>
                </>
              ) : null}
              <text
                x={x(index === 0 ? 0 : tier.min_qty) + 6}
                y={y(tier.unit_price_cents) - 7}
                className="tabular fill-[var(--ink-2)] text-[11px] font-medium"
              >
                {money(tier.unit_price_cents)}
              </text>
            </g>
          ))}
          <path
            d={path}
            fill="none"
            stroke="var(--ink-2)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          <text
            x={W - PAD.right}
            y={H - PAD.bottom + 16}
            textAnchor="end"
            className="fill-[var(--muted)] text-[10px]"
          >
            size of one order
          </text>
          {/* The pooled order: glides to its place as shops join. */}
          <g
            style={{
              transform: `translate(${x(qty)}px, ${y(price)}px)`,
              transition: "transform 380ms cubic-bezier(0.2, 0.8, 0.2, 1)",
            }}
          >
            <line y1={0} y2={H - PAD.bottom - y(price)} stroke="var(--honey)" strokeWidth={1.5} />
            <circle r={9} fill="var(--honey)" opacity={0.22} />
            <circle r={5.5} fill="var(--honey)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        </svg>
      ) : (
        <div style={{ height: H }} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------
// 2. Paying for what arrived
// ---------------------------------------------------------------------------------------

function ShortDelivery({ data }: { data: Explain }) {
  const { rows, ordered, hold_cents: hold, shop } = data.delivery;
  const short = Math.max(0, ordered - Math.max(2, Math.round(ordered * 0.12)));
  const frames = [];
  for (let value = ordered; value >= short; value -= 1) frames.push(value);
  const [delivered, setDelivered, card] = useDemonstration(frames, 260);
  const sliderId = useId();
  const row = rows[Math.max(0, Math.min(rows.length - 1, delivered))];
  const unit = data.product.unit;

  return (
    <Card className="p-5 sm:p-6">
      <div ref={card}>
        <h3 className="text-ink text-lg font-semibold">
          PayPal holds the money, then charges only for what arrives
        </h3>
        <p className="text-ink-2 mt-1 text-sm">
          {shop.name} orders {ordered} {unit}. On Wednesday PayPal holds {money(hold)} on the
          owner&apos;s account. Nothing is taken until the delivery is counted.
        </p>

        <div className="mt-5 grid grid-cols-3 gap-3 text-sm">
          <Figure
            icon={<Wallet className="h-3.5 w-3.5" aria-hidden />}
            tone="bg-honey-soft text-honey-ink"
            label="Held"
            cents={hold}
          />
          <Figure
            icon={<CheckCircle2 className="h-3.5 w-3.5" aria-hidden />}
            tone="bg-good-soft text-good-ink"
            label="Charged"
            cents={row.charged_cents}
          />
          <Figure
            icon={<Undo2 className="h-3.5 w-3.5" aria-hidden />}
            tone="bg-warning-soft text-warning-ink"
            label="Released"
            cents={row.released_cents}
          />
        </div>

        {/* The hold, split into what is charged and what goes back. */}
        <HoldBar
          className="mt-4"
          holdCents={hold}
          chargedCents={row.charged_cents}
          label={`Of the ${money(hold)} held, ${money(row.charged_cents)} is charged and ${money(row.released_cents)} is released.`}
        />

        <label htmlFor={sliderId} className="text-ink mt-4 block text-sm font-medium">
          On Thursday{" "}
          <span className="tabular">
            {row.delivered} of {ordered} {unit}
          </span>{" "}
          {row.delivered === 1 ? "arrives" : "arrive"}
        </label>
        <input
          id={sliderId}
          type="range"
          className="swarm-range mt-2 w-full"
          min={0}
          max={ordered}
          step={1}
          value={row.delivered}
          onChange={(event) => setDelivered(Number(event.target.value))}
          aria-valuetext={`${row.delivered} of ${ordered} ${unit} arrive: ${money(row.charged_cents)} charged, ${money(row.released_cents)} released`}
        />
        <p className="text-muted mt-3 text-xs">
          {row.delivered === 0
            ? "Nothing arrived, so nothing is charged and the whole hold is released."
            : row.released_cents === 0
              ? "Everything arrived, so the whole hold becomes the charge."
              : `PayPal captures ${money(row.charged_cents)} as the final amount and the other ${money(row.released_cents)} goes back to the owner. Nobody has to ask for a refund.`}{" "}
          The hold includes a {money(data.delivery.delivery_share_cents)} share of the{" "}
          {money(data.delivery.delivery_fee_cents)} delivery, which shrinks with what arrived.
        </p>

        {/* The PayPal calls behind it. */}
        <ol className="border-line mt-5 grid grid-cols-1 gap-3 border-t pt-4 text-xs sm:grid-cols-3">
          {[
            {
              when: "Wednesday",
              what: "Authorize",
              cents: hold,
              call: "orders/{id}/authorize",
            },
            {
              when: "Thursday",
              what: "Capture, final",
              cents: row.charged_cents,
              call: "authorizations/{id}/capture",
            },
            {
              when: "Straight after",
              what: "Rest of the hold released",
              cents: row.released_cents,
              call: "final_capture: true",
            },
          ].map((step, index) => (
            <li key={step.what} className="flex gap-2.5">
              <span className="bg-surface-2 text-ink-2 tabular grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold">
                {index + 1}
              </span>
              <span className="min-w-0">
                <span className="text-muted block">{step.when}</span>
                <span className="text-ink block font-medium">
                  {step.what} <span className="tabular">{money(step.cents)}</span>
                </span>
                <code className="text-muted block font-mono text-[10px] break-all">
                  {step.call}
                </code>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}

function Figure({
  icon,
  tone,
  label,
  cents,
}: {
  icon: React.ReactNode;
  /** Status colours for the chip; the number itself stays in ink. */
  tone: string;
  label: string;
  cents: number;
}) {
  return (
    <div>
      <div className="text-ink-2 flex items-center gap-1.5 text-xs font-medium">
        <span className={cx("grid h-5 w-5 place-items-center rounded-md", tone)}>{icon}</span>
        {label}
      </div>
      <div className="tabular text-ink mt-1 text-xl font-semibold">
        <AnimatedNumber value={cents} format={money} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------
// 3. An agent can't make up a price
// ---------------------------------------------------------------------------------------

/**
 * A real decision from this week's negotiation: the options code priced, the one that was
 * picked, and the rules the pick passed. Hover or tap an option to see what picking it would
 * have meant; none of them can go below the owner's floor.
 */
function GuardedChoice({ decision }: { decision: NonNullable<Explain["decision"]> }) {
  const options = [...decision.options].sort((a, b) => b.landed_total_cents - a.landed_total_cents);
  const [focus, setFocus] = useState(decision.chosen);
  const focused = options.find((option) => option.label === focus) ?? options[0];
  const chosen = options.find((option) => option.label === decision.chosen);
  const high = options[0].landed_total_cents;
  const low = options[options.length - 1].landed_total_cents;
  const span = Math.max(1, high - low);
  const byModel = decision.chosen_by === "llm";

  return (
    <Card className="p-5 sm:p-6 lg:col-span-2">
      <h3 className="text-ink text-lg font-semibold">An agent can&apos;t make up a price</h3>
      <p className="text-ink-2 mt-1 max-w-3xl text-sm">
        This is a real quote from this week&apos;s negotiation
        {decision.round ? `, round ${decision.round}` : ""}. {decision.supplier.name}&apos;s agent
        did not type a number. Code priced every option from the owner&apos;s price list and floor,
        the {byModel ? "language model" : "built-in policy"} picked one, and code checked the pick
        before it was sent.
      </p>

      <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div>
          <div className="text-ink-2 text-xs font-medium">
            1. The options code priced (landed total for the whole order)
          </div>
          <ul className="mt-2 space-y-1.5">
            {options.map((option) => {
              const picked = option.label === decision.chosen;
              const active = option.label === focused.label;
              const width = 28 + ((option.landed_total_cents - low) / span) * 72;
              return (
                <li key={option.label}>
                  <button
                    type="button"
                    onMouseEnter={() => setFocus(option.label)}
                    onFocus={() => setFocus(option.label)}
                    onClick={() => setFocus(option.label)}
                    aria-pressed={active}
                    className={cx(
                      "group relative flex w-full items-center justify-between gap-3 overflow-hidden rounded-lg border px-3 py-2 text-left text-sm transition",
                      active ? "border-line-strong" : "border-line",
                    )}
                  >
                    {/* How far down from the highest option this one sits. */}
                    <span
                      className={cx(
                        "absolute inset-y-0 left-0 transition-[width] duration-300",
                        picked ? "bg-honey-soft" : "bg-surface-2",
                      )}
                      style={{ width: `${width}%` }}
                      aria-hidden
                    />
                    <span
                      className={cx(
                        "relative inline-flex items-center gap-1.5",
                        picked ? "text-honey-ink font-semibold" : "text-ink",
                      )}
                    >
                      {picked ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : null}
                      {OPTION_WORDS[option.label] ?? option.label}
                      {picked ? <span className="sr-only"> (picked)</span> : null}
                    </span>
                    <span className="tabular text-ink relative font-medium">
                      {money(option.landed_total_cents)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="text-muted mt-2 text-xs" aria-live="polite">
            {focused.label === decision.chosen
              ? `Picked: ${(OPTION_WORDS[focused.label] ?? focused.label).toLowerCase()}, ${money(focused.landed_total_cents)}.`
              : chosen
                ? `"${OPTION_WORDS[focused.label] ?? focused.label}" would have been ${money(Math.abs(focused.landed_total_cents - chosen.landed_total_cents))} ${focused.landed_total_cents > chosen.landed_total_cents ? "dearer" : "cheaper"} than the pick. It was allowed, just not chosen.`
                : ""}
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <div className="text-ink-2 text-xs font-medium">
              2. {byModel ? "The language model picked one" : "The built-in policy picked one"}
            </div>
            <blockquote className="border-line-strong text-ink mt-2 border-l-2 pl-3 text-sm leading-relaxed">
              {decision.text}
            </blockquote>
            {byModel ? null : (
              <p className="text-muted mt-1.5 text-xs">
                No model key is set here, so the supplier&apos;s policy chose. With a key, the model
                chooses from the same list.
              </p>
            )}
          </div>
          <div>
            <div className="text-ink-2 text-xs font-medium">3. Code checked it before sending</div>
            <ul className="mt-2 space-y-1 text-xs">
              {decision.checked.map((rule) => (
                <li key={rule} className="text-ink-2 flex items-start gap-1.5">
                  <CheckCircle2 className="text-good-ink mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                  {rule}
                </li>
              ))}
            </ul>
          </div>
          {decision.order_id ? (
            <Link
              href={`/orders/${decision.order_id}`}
              className="text-ink inline-flex items-center gap-1 text-sm font-medium underline underline-offset-2"
            >
              See it in the conversation <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
