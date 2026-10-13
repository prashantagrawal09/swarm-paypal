"use client";

/**
 * The inspector: click any agent message and see how it came about. For a supplier's quote
 * or an award it shows the decision record kept by the server: the options code allowed,
 * who chose among them (the language model, the built-in policy, or a rule), and the rules
 * the choice passed before it was sent. For other messages it lays out the facts the
 * message carried.
 *
 * The point it makes: agents write the words; code computes every amount and checks every
 * action.
 */

import {
  ArrowRight,
  Bot,
  Calculator,
  CheckCircle2,
  Lock,
  Scale,
  ShieldCheck,
  Trophy,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";

import { cx } from "@/components/ui";
import type { AgentMessage, Decision, GroupOrder, Product } from "@/lib/api";
import { agentName, dayTime, humanize, money, slotColor } from "@/lib/format";
import { useNames } from "@/lib/use-names";

const InspectContext = createContext<(message: AgentMessage) => void>(() => undefined);

/** Open the inspector for a message. */
export function useInspect(): (message: AgentMessage) => void {
  return useContext(InspectContext);
}

/** Message types with something to explain beyond their text. */
const EXPLAINED = new Set([
  "QUOTE",
  "FINAL_QUOTE",
  "COUNTER",
  "FINAL_CALL",
  "AWARD",
  "INVOICE_REJECTED",
  "INVOICE_APPROVED",
  "CHARGED",
  "SURPLUS_OFFER",
  "EMERGENCY_REQUEST",
]);

/** Message types the server keeps a decision record for. */
const RECORDED = new Set(["QUOTE", "FINAL_QUOTE", "AWARD"]);

export function hasExplanation(message: AgentMessage): boolean {
  return EXPLAINED.has(message.type);
}

export function InspectorProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState<AgentMessage | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  const open = useCallback((next: AgentMessage) => {
    opener.current = document.activeElement as HTMLElement | null;
    setMessage(next);
  }, []);
  const close = useCallback(() => {
    setMessage(null);
    opener.current?.focus();
  }, []);

  useEffect(() => {
    if (!message) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [message, close]);

  return (
    <InspectContext.Provider value={open}>
      {children}
      {typeof document === "undefined"
        ? null
        : createPortal(
            <AnimatePresence>
              {message ? <Drawer key={message.id} message={message} onClose={close} /> : null}
            </AnimatePresence>,
            document.body,
          )}
    </InspectContext.Provider>
  );
}

// ---------------------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------------------

function Drawer({ message, onClose }: { message: AgentMessage; onClose: () => void }) {
  const names = useNames();
  const closeButton = useRef<HTMLButtonElement>(null);
  // Only quotes and awards have a decision record; asking for the rest would be a 404.
  const { data: decision } = useSWR<Decision>(
    RECORDED.has(message.type) ? `/api/agent-messages/${message.id}/decision` : null,
    { shouldRetryOnError: false, revalidateOnFocus: false },
  );
  const pathname = usePathname();
  const { data: groups } = useSWR<GroupOrder[]>("/api/group-orders");
  const order = groups?.find((group) => group.conversation_id === message.conversation_id);

  useEffect(() => {
    closeButton.current?.focus();
  }, []);

  return (
    <motion.div
      className="fixed inset-0 z-50 flex justify-end bg-black/30"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label="How this message came about"
        className="border-line-strong bg-surface flex h-full w-full max-w-md flex-col border-l shadow-2xl"
        initial={{ x: 32 }}
        animate={{ x: 0 }}
        exit={{ x: 32 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
      >
        <header className="border-line flex items-start gap-3 border-b px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="text-muted text-[11px] font-medium tracking-wide uppercase">
              {humanize(message.type)} · {dayTime(message.at)}
            </div>
            <div className="text-ink mt-1 flex flex-wrap items-center gap-x-1.5 text-sm font-semibold">
              {agentName(message.from, names)}
              <ArrowRight className="text-muted h-3.5 w-3.5" aria-label="to" />
              <span className="text-ink-2 font-medium">{agentName(message.to, names)}</span>
            </div>
          </div>
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            className="text-ink-2 hover:bg-surface-2 hover:text-ink -m-1 rounded-lg p-1.5"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="feed min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
          <blockquote className="border-line-strong text-ink border-l-2 pl-3 text-sm leading-relaxed whitespace-pre-line">
            {message.text}
          </blockquote>

          {decision?.kind === "quote" ? <QuoteDecision decision={decision} /> : null}
          {decision?.kind === "award" ? <AwardDecision decision={decision} names={names} /> : null}

          <Facts message={message} names={names} />
        </div>

        <footer className="border-line text-ink-2 border-t px-5 py-3.5 text-xs">
          <p>
            Agents write the words. Code computes every amount and checks every action against the
            owner&apos;s rules before it happens.
          </p>
          {order && pathname !== `/orders/${order.id}` ? (
            <Link
              href={`/orders/${order.id}`}
              onClick={onClose}
              className="text-ink mt-2 inline-flex items-center gap-1 font-medium underline underline-offset-2"
            >
              Open this group order <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          ) : null}
        </footer>
      </motion.aside>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------------------
// Decision records
// ---------------------------------------------------------------------------------------

function Step({
  number,
  icon,
  title,
  children,
}: {
  number: number;
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="relative pl-10">
      <span
        className="bg-surface-2 text-ink absolute top-0 left-0 grid h-7 w-7 place-items-center rounded-full"
        aria-hidden
      >
        {icon}
      </span>
      <h3 className="text-ink pt-0.5 text-sm font-semibold">
        <span className="sr-only">Step {number}: </span>
        {title}
      </h3>
      <div className="text-ink-2 mt-1.5 text-xs leading-relaxed">{children}</div>
    </li>
  );
}

const OPTION_WORDS: Record<string, string> = {
  hold: "Hold the price",
  small: "A small step down",
  beat: "Just beat the best rival",
  deep: "A big step down",
  floor: "Go to the owner's floor",
};

function chooser(by: string): string {
  if (by === "llm") return "The language model chose";
  if (by === "rule") return "A rule chose";
  return "The built-in policy chose";
}

function QuoteDecision({ decision }: { decision: Decision }) {
  const chosen = OPTION_WORDS[decision.chosen] ?? decision.chosen;
  return (
    <section aria-label="How this quote was decided">
      <h2 className="text-ink text-xs font-semibold tracking-wide uppercase">
        How this was decided
      </h2>
      <ol className="mt-3 space-y-5">
        <Step
          number={1}
          icon={<Calculator className="h-3.5 w-3.5" />}
          title="Code priced the options"
        >
          <p>
            Worked out from the owner&apos;s price list and floor prices. The agent could only pick
            one of these; it cannot type a price.
          </p>
          {decision.options ? (
            <ul className="border-line mt-2 divide-y divide-[var(--line)] rounded-lg border">
              {[...decision.options]
                .sort((a, b) => b.landed_total_cents - a.landed_total_cents)
                .map((option) => {
                  const picked = option.label === decision.chosen;
                  return (
                    <li
                      key={option.label}
                      className={cx(
                        "flex items-center justify-between gap-3 px-3 py-2",
                        picked && "bg-honey-soft",
                      )}
                    >
                      <span
                        className={cx(
                          "inline-flex items-center gap-1.5",
                          picked ? "text-honey-ink font-semibold" : "text-ink-2",
                        )}
                      >
                        {picked ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : null}
                        {OPTION_WORDS[option.label] ?? option.label}
                        {picked ? <span className="sr-only"> (chosen)</span> : null}
                      </span>
                      <span
                        className={cx(
                          "tabular",
                          picked ? "text-honey-ink font-semibold" : "text-ink",
                        )}
                      >
                        {money(option.landed_total_cents)}
                      </span>
                    </li>
                  );
                })}
            </ul>
          ) : null}
          <p className="text-muted mt-2 flex items-start gap-1.5">
            <Lock className="mt-px h-3 w-3 shrink-0" aria-hidden />
            {decision.options
              ? "A supplier's options are private to its owner. The buyers' side never receives them; you can see them because this demo lets you look inside every agent."
              : "A supplier's options are private to its owner, so they are not shown here."}
          </p>
        </Step>
        <Step
          number={2}
          icon={<Bot className="h-3.5 w-3.5" />}
          title={`${chooser(decision.chosen_by)}: ${chosen.toLowerCase()}`}
        >
          {decision.chosen_by === "llm" ? (
            <p>It picked from the list above and wrote the message. It did not set any number.</p>
          ) : (
            <p>
              No language model answered (no key is set, or the call failed), so the supplier&apos;s
              built-in policy picked from the same list. With a model, the model picks; the list and
              the checks stay the same.
            </p>
          )}
        </Step>
        <Step
          number={3}
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
          title="Code checked it before sending"
        >
          <ul className="space-y-1">
            {(decision.checked ?? []).map((rule) => (
              <li key={rule} className="flex items-start gap-1.5">
                <CheckCircle2 className="text-good-ink mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>
                  {rule}
                  <span className="sr-only"> (passed)</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2">
            Had any of these failed, the quote would have been refused and logged.
          </p>
        </Step>
      </ol>
    </section>
  );
}

function AwardDecision({ decision, names }: { decision: Decision; names: Record<string, string> }) {
  return (
    <section aria-label="How this award was decided">
      <h2 className="text-ink text-xs font-semibold tracking-wide uppercase">
        How this was decided
      </h2>
      <ol className="mt-3 space-y-5">
        <Step number={1} icon={<Scale className="h-3.5 w-3.5" />} title="The rule, fixed in code">
          <p>{decision.rule}</p>
        </Step>
        <Step
          number={2}
          icon={<Calculator className="h-3.5 w-3.5" />}
          title={`The final quotes after ${decision.rounds ?? 3} rounds`}
        >
          <ul className="border-line divide-y divide-[var(--line)] rounded-lg border">
            {(decision.ranking ?? []).map((row) => {
              const won = row.supplier === decision.chosen;
              return (
                <li
                  key={row.supplier}
                  className="flex items-center justify-between gap-3 px-3 py-2"
                >
                  <span className="text-ink inline-flex min-w-0 items-center gap-1.5 font-medium">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: slotColor(row.supplier) }}
                      aria-hidden
                    />
                    <span className="truncate">{names[row.supplier] ?? row.supplier}</span>
                    {won ? (
                      <span className="bg-good-soft text-good-ink inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-semibold">
                        <Trophy className="h-3 w-3" aria-hidden /> lowest
                      </span>
                    ) : null}
                  </span>
                  <span className="text-ink-2 shrink-0 text-right">
                    <span className="tabular text-ink font-medium">
                      {money(row.landed_total_cents)}
                    </span>
                    <span className="text-muted block text-[10px]">
                      reliability {row.reliability}
                      {row.eligible ? "" : " (below the bar)"}
                    </span>
                  </span>
                </li>
              );
            })}
            {(decision.declined ?? []).map((row) => (
              <li key={row.supplier} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="text-ink-2 inline-flex min-w-0 items-center gap-1.5">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: slotColor(row.supplier) }}
                    aria-hidden
                  />
                  <span className="truncate">{names[row.supplier] ?? row.supplier}</span>
                </span>
                <span className="text-muted shrink-0 text-right">
                  didn&apos;t quote: {row.reason}
                </span>
              </li>
            ))}
          </ul>
        </Step>
        <Step
          number={3}
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
          title="No model was asked who should win"
        >
          <p>
            The rule picked {names[decision.chosen] ?? decision.chosen}. The coordinator&apos;s
            agent is refused if it tries to award anyone else. The model only wrote the
            announcement.
          </p>
        </Step>
      </ol>
    </section>
  );
}

// ---------------------------------------------------------------------------------------
// What the message carried
// ---------------------------------------------------------------------------------------

type Issue = { text?: string; agreed_cents?: number; charged_cents?: number; qty?: number };

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-ink-2">{label}</dt>
      <dd className="tabular text-ink text-right font-medium">{children}</dd>
    </div>
  );
}

function Facts({ message, names }: { message: AgentMessage; names: Record<string, string> }) {
  const { data: products } = useSWR<Product[]>("/api/products");
  const payload = message.payload;
  const cents = (key: string) =>
    typeof payload[key] === "number" ? (payload[key] as number) : null;
  const productName = (code: string) => {
    const product = products?.find((p) => p.product === code);
    if (!product) return code;
    return `${product.name.charAt(0).toUpperCase()}${product.name.slice(1)}, per ${product.unit}`;
  };
  const prices = payload.unit_prices as Record<string, number> | undefined;
  const heading = "text-ink text-xs font-semibold tracking-wide uppercase";
  const list = "divide-y divide-[var(--line)] text-xs";

  if (message.type === "QUOTE" || message.type === "FINAL_QUOTE" || message.type === "AWARD") {
    return (
      <section>
        <h2 className={heading}>The numbers</h2>
        <dl className={cx(list, "mt-2")}>
          {Object.entries(prices ?? {}).map(([code, price]) => (
            <Row key={code} label={productName(code)}>
              {money(price)}
            </Row>
          ))}
          {cents("items_total_cents") !== null ? (
            <Row label="Goods">{money(cents("items_total_cents"))}</Row>
          ) : null}
          {cents("delivery_fee_cents") !== null ? (
            <Row label="One delivery, shared">{money(cents("delivery_fee_cents"))}</Row>
          ) : null}
          <Row label="Landed total">{money(cents("landed_total_cents"))}</Row>
        </dl>
        {Array.isArray(payload.excluded) && payload.excluded.length ? (
          <p className="text-ink-2 mt-3 text-xs">
            Left out of this deal:{" "}
            {(payload.excluded as { reason?: string }[]).map((e) => e.reason).join("; ")}. Their
            preferences are rules, so their agents could not accept.
          </p>
        ) : null}
      </section>
    );
  }

  if (message.type === "COUNTER" || message.type === "FINAL_CALL") {
    return (
      <section>
        <h2 className={heading}>What the supplier was told</h2>
        <dl className={cx(list, "mt-2")}>
          <Row label="Best competing landed price">
            {money(cents("best_competing_landed_cents") ?? cents("target_landed_cents"))}
          </Row>
          <Row label="Round">{String(payload.round ?? "")} of 3</Row>
        </dl>
        <p className="text-ink-2 mt-3 text-xs">
          Only the price to beat. Never who offered it, and never anyone&apos;s floor: a
          counter-offer that mentions a floor is refused by the coordinator&apos;s own rules.
        </p>
      </section>
    );
  }

  if (message.type === "INVOICE_REJECTED" || message.type === "INVOICE_APPROVED") {
    const report = (payload.report ?? {}) as {
      issues?: Issue[];
      expected_total_cents?: number;
      invoiced_total_cents?: number;
      overcharge_cents?: number;
    };
    return (
      <section>
        <h2 className={heading}>The line-by-line check</h2>
        <dl className={cx(list, "mt-2")}>
          <Row label="Invoiced">{money(report.invoiced_total_cents)}</Row>
          <Row label="Agreed in the deal">{money(report.expected_total_cents)}</Row>
          {report.overcharge_cents ? (
            <Row label="Overcharge">{money(report.overcharge_cents)}</Row>
          ) : null}
        </dl>
        {report.issues?.length ? (
          <ul className="text-ink-2 mt-3 space-y-1 text-xs">
            {report.issues.map((issue, index) => (
              <li key={index}>{issue.text}</li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-2 mt-3 text-xs">Every line matched the awarded quote.</p>
        )}
        <p className="text-ink-2 mt-3 text-xs">
          The check compares each line with the awarded quote in code. Nothing is paid until an
          invoice passes it.
        </p>
      </section>
    );
  }

  if (message.type === "CHARGED") {
    return (
      <section>
        <h2 className={heading}>What PayPal did</h2>
        <dl className={cx(list, "mt-2")}>
          <Row label="Captured">{money(cents("captured_cents"))}</Row>
          <Row label="Released back to the owner">{money(cents("released_cents"))}</Row>
        </dl>
        <p className="text-ink-2 mt-3 text-xs">
          The capture is for what the owner confirmed arrived, marked final, so PayPal releases the
          rest of the hold by itself.
        </p>
      </section>
    );
  }

  // Anything else: the facts it carried, minus plumbing (buttons, references, IDs).
  const facts = Object.entries(payload).filter(
    ([key, value]) =>
      !["actions", "ref", "kind", "answered", "report"].includes(key) &&
      !key.endsWith("_id") &&
      (typeof value === "number" || typeof value === "string" || typeof value === "boolean"),
  );
  if (!facts.length) return null;
  return (
    <section>
      <h2 className={heading}>What it carried</h2>
      <dl className={cx(list, "mt-2")}>
        {facts.map(([key, value]) => (
          <Row key={key} label={humanize(key.replace(/_cents$/, "").replace(/_m$/, " (metres)"))}>
            {key.endsWith("_cents") && typeof value === "number"
              ? money(value)
              : typeof value === "boolean"
                ? value
                  ? "yes"
                  : "no"
                : String(names[String(value)] ?? value)}
          </Row>
        ))}
      </dl>
    </section>
  );
}
