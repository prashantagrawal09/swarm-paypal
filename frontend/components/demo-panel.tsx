"use client";

/**
 * The demo panel: drive the Swarm Clock through the week, arm the week's surprises, play an
 * owner on their phone, decide escalated claims, and see what the server is running with.
 */

import {
  AlertTriangle,
  Bot,
  Check,
  FastForward,
  FileWarning,
  Leaf,
  type LucideIcon,
  PackageMinus,
  RotateCcw,
  Send,
  ShieldCheck,
  SkipForward,
  PackageX,
  Siren,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import useSWR from "swr";

import { DemoKeyPrompt } from "@/components/demo-key-prompt";
import { OwnerPhone } from "@/components/owner-phone";
import { Button, Card, CardHeader, cx, Empty, ModeBadge, StatusPill } from "@/components/ui";
import { WeekStepper } from "@/components/week-stepper";
import {
  ApiError,
  type ClaimRow,
  type DemoState,
  mediaUrl,
  type Mode,
  post,
  type Product,
  type ShopSummary,
  type SupplierSummary,
} from "@/lib/api";
import { dayTime, humanize, money, time } from "@/lib/format";

type Busy = string | null;

export function DemoPanel() {
  const { data: state, mutate } = useSWR<DemoState>("/api/demo/state");
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<{ tone: "good" | "critical"; text: string } | null>(null);
  const [needKey, setNeedKey] = useState(false);
  const [phoneShop, setPhoneShop] = useState("cafe-mei");

  const act = useCallback(
    async (label: string, path: string, body?: unknown, done?: string) => {
      setBusy(label);
      setNotice(null);
      try {
        await post(path, body);
        if (done) setNotice({ tone: "good", text: done });
        await mutate();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) setNeedKey(true);
        setNotice({
          tone: "critical",
          text: err instanceof Error ? err.message : "That didn't work",
        });
      } finally {
        setBusy(null);
      }
    },
    [mutate],
  );

  const next = state?.steps.find((s) => s.status === "next");
  const finished = state ? state.steps.every((s) => s.status === "done") : false;
  const locked = Boolean(state?.running) || busy !== null;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-ink text-2xl font-semibold tracking-tight">Demo panel</h1>
          <p className="text-ink-2 mt-1 max-w-2xl text-sm">
            Change what goes wrong this week, play any shop owner on their phone, and decide the
            claims that need a person. Every button runs the real code path, with real PayPal
            sandbox calls for REAL accounts. The{" "}
            <Link
              href="/live"
              className="text-ink decoration-line-strong font-medium underline underline-offset-2"
            >
              live board
            </Link>{" "}
            shows it all happening and can run the week by itself.
          </p>
        </div>
        {state && !state.demo_mode ? (
          <StatusPill tone="warning">Demo controls are off on this server</StatusPill>
        ) : null}
      </div>

      {needKey ? <DemoKeyPrompt className="mt-4" onSaved={() => setNeedKey(false)} /> : null}

      {notice ? (
        <div
          role="status"
          className={cx(
            "mt-4 flex items-start gap-2 rounded-xl px-3 py-2 text-sm",
            notice.tone === "good"
              ? "bg-good-soft text-good-ink"
              : "bg-critical-soft text-critical-ink",
          )}
        >
          {notice.tone === "good" ? (
            <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          )}
          <span className="flex-1">{notice.text}</span>
          <button
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="opacity-70 hover:opacity-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-6">
          {/* Clock and controls */}
          <Card>
            <CardHeader
              title="The week"
              subtitle={
                state
                  ? `Swarm Clock: ${state.local} (Singapore) · week of ${state.week}`
                  : "Loading..."
              }
              action={state?.running ? <StatusPill tone="busy">Running</StatusPill> : null}
            />
            <div className="px-5 pb-5">
              {state ? (
                <WeekStepper steps={state.steps} running={state.running} />
              ) : (
                <div className="h-16" />
              )}
              <div className="mt-5 flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  busy={busy === "advance"}
                  disabled={locked}
                  onClick={() =>
                    act(
                      "advance",
                      "/api/demo/advance?paced=true",
                      undefined,
                      finished
                        ? "Starting next week. Watch the live board."
                        : `Running ${next?.title ?? "the next step"}. Watch the live board.`,
                    )
                  }
                >
                  <SkipForward className="h-4 w-4" aria-hidden />
                  {finished ? "Start next week" : next ? `Next: ${next.title}` : "Next step"}
                </Button>
                <Button
                  variant="honey"
                  busy={busy === "run" || state?.running}
                  disabled={locked || finished}
                  onClick={() =>
                    act(
                      "run",
                      "/api/demo/run-week",
                      undefined,
                      "Running the rest of the week. Watch the live board.",
                    )
                  }
                >
                  <FastForward className="h-4 w-4" aria-hidden />
                  {state?.running ? "Running the week" : "Run the rest of the week"}
                </Button>
                <Button
                  variant="danger"
                  className="ml-auto"
                  busy={busy === "reset"}
                  disabled={locked}
                  onClick={() => {
                    if (
                      window.confirm(
                        "Reset the demo? This wipes this week's orders and payments and reseeds Tiong Bahru.",
                      )
                    ) {
                      void act(
                        "reset",
                        "/api/demo/reset",
                        undefined,
                        "Fresh demo world. The clock is back on Monday 08:00.",
                      );
                    }
                  }}
                >
                  <RotateCcw className="h-4 w-4" aria-hidden /> Reset
                </Button>
              </div>
              {next ? (
                <p className="text-ink-2 mt-3 text-xs">
                  <span className="text-ink font-medium">{next.title}</span> ({dayTime(next.at)}):{" "}
                  {next.description}
                </p>
              ) : null}
            </div>
          </Card>

          <Injections state={state} act={act} busy={busy} locked={locked} />

          <ClaimsQueue onUnauthorized={() => setNeedKey(true)} />

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Environment state={state} />
            <ActivityLog state={state} />
          </div>
        </div>

        {/* Owner's phone */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <div className="mb-3 flex items-baseline justify-between px-1">
            <h2 className="text-ink text-sm font-semibold">Be the owner</h2>
            <span className="text-muted text-xs">Same chat as Telegram</span>
          </div>
          <OwnerPhone
            shop={phoneShop}
            shops={shops}
            onShopChange={setPhoneShop}
            onUnauthorized={() => setNeedKey(true)}
            clock={state ? time(state.now) : undefined}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------
// Injections
// ---------------------------------------------------------------------------------------

type Act = (label: string, path: string, body?: unknown, done?: string) => Promise<void>;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="text-ink-2 flex min-w-0 flex-col gap-1 text-[11px] font-medium">
      {label}
      {children}
    </label>
  );
}

const inputClass =
  "h-8 w-full min-w-0 rounded-lg border border-line bg-surface px-2 text-xs text-ink outline-none focus:border-line-strong";

function Injections({
  state,
  act,
  busy,
  locked,
}: {
  state?: DemoState;
  act: Act;
  busy: Busy;
  locked: boolean;
}) {
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const { data: suppliers } = useSWR<SupplierSummary[]>("/api/suppliers");
  const { data: products } = useSWR<Product[]>("/api/products");
  const [draft, setDraft] = useState<Record<string, Record<string, unknown>>>({});

  useEffect(() => {
    // Start from the server's scenario; local edits stay until sent.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (state?.scenario) setDraft((current) => ({ ...state.scenario, ...current }));
  }, [state?.scenario]);

  const value = (kind: string, key: string) =>
    draft[kind]?.[key] ?? state?.scenario[kind]?.[key] ?? "";
  const set = (kind: string, key: string, v: unknown) =>
    setDraft((current) => ({ ...current, [kind]: { ...current[kind], [key]: v } }));
  // Whether an optional surprise is in the week is the server's to say, never a local edit.
  const params = (kind: string) =>
    Object.fromEntries(Object.entries(draft[kind] ?? {}).filter(([key]) => key !== "scheduled"));
  const send = (kind: string, now: boolean, done: string) =>
    act(`${kind}:${now}`, "/api/demo/inject", { kind, params: params(kind), now }, done);
  /** Puts an optional surprise into the week's script, or takes it out again. */
  const schedule = (kind: string, on: boolean, done: string) =>
    act(
      `${kind}:false`,
      "/api/demo/inject",
      { kind, params: { ...params(kind), scheduled: on }, now: false },
      done,
    );

  const shopSelect = (kind: string) => (
    <select
      className={inputClass}
      value={String(value(kind, "shop"))}
      onChange={(e) => set(kind, "shop", e.target.value)}
    >
      {(shops ?? []).map((s) => (
        <option key={s.code} value={s.code}>
          {s.name}
        </option>
      ))}
    </select>
  );
  const productSelect = (kind: string, category?: string) => (
    <select
      className={inputClass}
      value={String(value(kind, "product"))}
      onChange={(e) => set(kind, "product", e.target.value)}
    >
      {(products ?? [])
        .filter((p) => !category || p.category === category)
        .map((p) => (
          <option key={p.product} value={p.product}>
            {p.name}
          </option>
        ))}
    </select>
  );
  const number = (
    kind: string,
    key: string,
    props: { min?: number; max?: number; step?: number } = {},
  ) => (
    <input
      type="number"
      className={cx(inputClass, "tabular")}
      value={String(value(kind, key))}
      onChange={(e) => set(kind, key, e.target.value === "" ? "" : Number(e.target.value))}
      {...props}
    />
  );

  const flashSupplier = String(value("flash_deal", "supplier"));
  const flashSkus = (products ?? []).flatMap((p) =>
    p.skus.filter((s) => s.supplier === flashSupplier),
  );

  const cards: {
    kind: string;
    title: string;
    icon: LucideIcon;
    when: string;
    fields: React.ReactNode;
    now?: string;
    /** Not in the week's script unless added: a switch instead of Save. */
    optional?: { add: string; remove: string; added: string; removed: string };
    /** What to say once it has been done now. */
    done?: string;
  }[] = [
    {
      kind: "short_delivery",
      title: "Short delivery",
      icon: PackageMinus,
      when: "Thursday delivery",
      fields: (
        <>
          <Field label="Shop">{shopSelect("short_delivery")}</Field>
          <Field label="Product">
            <select
              className={inputClass}
              value={String(value("short_delivery", "product"))}
              onChange={(e) => {
                const product = (products ?? []).find((p) => p.product === e.target.value);
                set("short_delivery", "product", e.target.value);
                if (product) set("short_delivery", "category", product.category);
              }}
            >
              {(products ?? []).map((p) => (
                <option key={p.product} value={p.product}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Share delivered">
            <select
              className={inputClass}
              value={String(value("short_delivery", "fraction"))}
              onChange={(e) => set("short_delivery", "fraction", Number(e.target.value))}
            >
              {[0.5, 0.75, 0.8, 0.9].map((f) => (
                <option key={f} value={f}>
                  {Math.round(f * 100)}%
                </option>
              ))}
            </select>
          </Field>
        </>
      ),
    },
    {
      kind: "wrong_price_invoice",
      title: "Overcharged invoice",
      icon: FileWarning,
      when: "Thursday settlement",
      fields: (
        <>
          <Field label="Category">
            <select
              className={inputClass}
              value={String(value("wrong_price_invoice", "category"))}
              onChange={(e) => set("wrong_price_invoice", "category", e.target.value)}
            >
              {["DAIRY", "PANTRY", "PRODUCE", "PACKAGING"].map((c) => (
                <option key={c} value={c}>
                  {humanize(c)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Product">
            {productSelect("wrong_price_invoice", String(value("wrong_price_invoice", "category")))}
          </Field>
          <Field label="Extra per unit (cents)">
            {number("wrong_price_invoice", "markup_cents", { min: 1, max: 500 })}
          </Field>
        </>
      ),
    },
    {
      kind: "flash_deal",
      title: "Supplier flash deal",
      icon: Zap,
      when: "Wednesday",
      fields: (
        <>
          <Field label="Supplier">
            <select
              className={inputClass}
              value={flashSupplier}
              onChange={(e) => set("flash_deal", "supplier", e.target.value)}
            >
              {(suppliers ?? []).map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Item">
            <select
              className={inputClass}
              value={String(value("flash_deal", "sku"))}
              onChange={(e) => set("flash_deal", "sku", e.target.value)}
            >
              {flashSkus.map((s) => (
                <option key={s.sku} value={s.sku}>
                  {s.name} ({s.brand})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Quantity">{number("flash_deal", "qty", { min: 1, max: 500 })}</Field>
          <Field label="Discount %">
            {number("flash_deal", "discount_pct", { min: 5, max: 70 })}
          </Field>
        </>
      ),
    },
    {
      kind: "surplus",
      title: "Surplus stock",
      icon: Leaf,
      when: "Friday",
      now: "Post it now",
      fields: (
        <>
          <Field label="Shop">{shopSelect("surplus")}</Field>
          <Field label="Product">{productSelect("surplus")}</Field>
          <Field label="Quantity">{number("surplus", "qty", { min: 1, max: 100 })}</Field>
          <Field label="Days to expiry">{number("surplus", "days_left", { min: 1, max: 7 })}</Field>
        </>
      ),
    },
    {
      kind: "emergency",
      title: "Emergency borrow",
      icon: Siren,
      when: "Saturday",
      now: "Ask the neighbours now",
      fields: (
        <>
          <Field label="Shop">{shopSelect("emergency")}</Field>
          <Field label="Product">{productSelect("emergency")}</Field>
          <Field label="Quantity">{number("emergency", "qty", { min: 1, max: 20 })}</Field>
        </>
      ),
    },
    {
      kind: "damage_claim",
      title: "Damage claim",
      icon: PackageX,
      when: "Thursday, if added",
      now: "Report it now",
      optional: {
        add: "Add to Thursday",
        remove: "Remove from Thursday",
        added:
          "Damage claim added to Thursday. It is reported once the delivery is charged, so that much is held back from the supplier until you decide it below.",
        removed: "Damage claim taken out of this week.",
      },
      done: "Claim filed. It came without a photo, so it is waiting below for a person: approve it to see PayPal refund the original payment.",
      fields: (
        <>
          <Field label="Shop">{shopSelect("damage_claim")}</Field>
          <Field label="Product">{productSelect("damage_claim")}</Field>
          <Field label="Units damaged">{number("damage_claim", "qty", { min: 1, max: 20 })}</Field>
        </>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Surprises this week"
        subtitle="Each one is armed for its day. Change the details, then save; surplus, emergency and a damage claim can also happen right now."
      />
      <div className="border-line bg-line grid grid-cols-1 gap-px overflow-hidden border-t sm:grid-cols-2">
        {cards.map((card) => {
          const Icon = card.icon;
          const scheduled = Boolean(card.optional && state?.scenario[card.kind]?.scheduled);
          return (
            <div key={card.kind} className="bg-surface flex flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <span
                  className="bg-surface-2 text-ink-2 grid h-7 w-7 place-items-center rounded-lg"
                  aria-hidden
                >
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <span className="text-ink text-sm font-medium">{card.title}</span>
                {scheduled ? (
                  <span className="ml-auto">
                    <StatusPill tone="good">On for Thursday</StatusPill>
                  </span>
                ) : (
                  <span className="text-muted ml-auto text-[11px]">{card.when}</span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">{card.fields}</div>
              <div className="mt-auto flex flex-wrap gap-2">
                {card.optional && scheduled ? (
                  <Button
                    className="h-8 py-0 text-xs"
                    disabled={locked || busy === `${card.kind}:false`}
                    onClick={() => schedule(card.kind, true, `${card.title} updated for Thursday.`)}
                  >
                    Save
                  </Button>
                ) : null}
                {card.optional ? (
                  <Button
                    className="h-8 py-0 text-xs"
                    busy={busy === `${card.kind}:false`}
                    disabled={locked}
                    aria-pressed={scheduled}
                    onClick={() =>
                      schedule(
                        card.kind,
                        !scheduled,
                        scheduled ? card.optional!.removed : card.optional!.added,
                      )
                    }
                  >
                    {scheduled ? card.optional.remove : card.optional.add}
                  </Button>
                ) : (
                  <Button
                    className="h-8 py-0 text-xs"
                    busy={busy === `${card.kind}:false`}
                    disabled={locked}
                    onClick={() => send(card.kind, false, `${card.title} armed for ${card.when}.`)}
                  >
                    Save
                  </Button>
                )}
                {card.now ? (
                  <Button
                    variant="honey"
                    className="h-8 py-0 text-xs"
                    busy={busy === `${card.kind}:true`}
                    disabled={locked}
                    onClick={() =>
                      send(
                        card.kind,
                        true,
                        card.done ?? `${card.title}: done. Watch the board and the owner's phone.`,
                      )
                    }
                  >
                    <Send className="h-3.5 w-3.5" aria-hidden />
                    {card.now}
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
        <div className="bg-surface text-ink-2 hidden flex-col justify-center gap-2 p-4 text-xs sm:col-span-2 sm:flex">
          <p className="text-ink text-sm font-medium">How these play out</p>
          <p>
            Short delivery and the overcharged invoice both play out on Thursday; the smaller charge
            and the rejected invoice show on the live board. Wednesday&apos;s flash deal is bought
            by shop agents only within each owner&apos;s limit. A damage claim is not in the script:
            add it to Thursday and that much is held back from the supplier until you decide it
            under Claims, or report one at any time after Thursday. Approve it and PayPal refunds
            the original payment.
          </p>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------------------
// Claims, environment, log
// ---------------------------------------------------------------------------------------

type ClaimVerdict = {
  decision: string;
  refund: { amount_cents: number; paypal_id: string | null; mode: Mode } | null;
};

/** What the claims agent made of the evidence, in one line. */
function agentLine(claim: ClaimRow): string | null {
  const a = claim.assessment as {
    evidence?: string;
    confidence?: number;
    source?: string;
    decision_reason?: string;
  };
  // Nothing read a photo: say why a person has it, and no made-up confidence.
  if (a.source === "fallback") return a.decision_reason ?? a.evidence ?? null;
  if (!a.evidence) return null;
  return typeof a.confidence === "number"
    ? `${a.evidence} (${Math.round(a.confidence * 100)}% sure)`
    : a.evidence;
}

function ClaimsQueue({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { data: claims, mutate } = useSWR<ClaimRow[]>("/api/claims?open_only=true");
  const [busy, setBusy] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<{
    tone: "good" | "neutral" | "critical";
    text: string;
    paypalId?: string | null;
    mode?: Mode;
  } | null>(null);

  async function decide(claim: ClaimRow, approve: boolean) {
    setBusy(claim.id);
    setOutcome(null);
    const shop = claim.shop?.name ?? "the shop";
    try {
      const verdict = await post<ClaimVerdict>(`/api/demo/claims/${claim.id}/decide`, {
        approve,
        note: approve ? "Approved by operator" : "Rejected by operator",
      });
      await mutate();
      setOutcome(
        verdict.refund
          ? {
              tone: "good",
              text: `PayPal refunded ${money(verdict.refund.amount_cents)} to ${shop}, back onto the payment it came from.`,
              paypalId: verdict.refund.paypal_id,
              mode: verdict.refund.mode,
            }
          : { tone: "neutral", text: `Claim rejected. ${shop} has been told; no money moved.` },
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else
        setOutcome({
          tone: "critical",
          text: err instanceof ApiError ? err.message : "That didn't go through. Try again.",
        });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card id="claims" className="scroll-mt-24">
      <CardHeader
        title="Claims waiting for a person"
        subtitle="The claims agent refunds clear cases itself and sends the rest here."
        icon={ShieldCheck}
      />
      <div className="px-5 pb-5">
        {outcome ? (
          <div
            role="status"
            className={cx(
              "mb-3 flex items-start gap-2 rounded-xl px-3 py-2.5 text-sm",
              outcome.tone === "good"
                ? "bg-good-soft text-good-ink"
                : outcome.tone === "critical"
                  ? "bg-critical-soft text-critical-ink"
                  : "bg-surface-2 text-ink-2",
            )}
          >
            {outcome.tone === "critical" ? (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            ) : (
              <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <p>{outcome.text}</p>
              {outcome.paypalId ? (
                <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                  <span>
                    Refund <span className="font-mono">{outcome.paypalId}</span>
                  </span>
                  {outcome.mode ? <ModeBadge mode={outcome.mode} compact /> : null}
                  <Link href="/money" className="font-medium underline underline-offset-2">
                    See it on the Money page
                  </Link>
                </p>
              ) : null}
            </div>
            <button
              onClick={() => setOutcome(null)}
              aria-label="Dismiss"
              className="opacity-70 hover:opacity-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}
        {!claims || claims.length === 0 ? (
          outcome ? null : (
            <Empty>
              No open claims. An owner reporting damage without a clear photo lands here.
            </Empty>
          )
        ) : (
          <ul className="space-y-3">
            {claims.map((claim) => {
              const photo = mediaUrl(claim.photo_url);
              const says = agentLine(claim);
              return (
                <li key={claim.id} className="border-line flex gap-3 rounded-xl border p-3">
                  {photo ? (
                    // Claim photos come from the API's media store, which next/image can't optimise.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={photo}
                      alt="Photo sent with the claim"
                      className="h-20 w-20 shrink-0 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="bg-surface-2 text-muted grid h-20 w-20 shrink-0 place-items-center rounded-lg text-[11px]">
                      No photo
                    </div>
                  )}
                  <div className="min-w-0 flex-1 text-sm">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                      <span className="text-ink font-medium">{claim.shop?.name ?? "Shop"}</span>
                      <span className="tabular text-ink font-semibold">
                        {money(claim.amount_cents)}
                      </span>
                    </div>
                    <p className="text-ink-2 mt-0.5">
                      {claim.what ?? `${claim.qty} units`}, {humanize(claim.type).toLowerCase()}
                    </p>
                    {claim.description ? (
                      <p className="text-ink-2 mt-1">&ldquo;{claim.description}&rdquo;</p>
                    ) : null}
                    {says ? (
                      <p className="text-muted mt-1 flex items-start gap-1.5 text-xs">
                        <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                        <span>Claims agent: {says}</span>
                      </p>
                    ) : claim.note ? (
                      <p className="text-muted mt-1 text-xs">{claim.note}</p>
                    ) : null}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        className="h-8 py-0 text-xs"
                        variant="primary"
                        busy={busy === claim.id}
                        onClick={() => decide(claim, true)}
                      >
                        Refund {money(claim.amount_cents)}
                      </Button>
                      <Button
                        className="h-8 py-0 text-xs"
                        variant="danger"
                        disabled={busy === claim.id}
                        onClick={() => decide(claim, false)}
                      >
                        Reject
                      </Button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

function Environment({ state }: { state?: DemoState }) {
  const rows: [string, React.ReactNode][] = state
    ? [
        ["PayPal", `${state.paypal_env} environment`],
        [
          "Shops",
          <span key="shops" className="inline-flex flex-wrap items-center gap-1.5">
            {Object.entries(state.modes.shops).map(([mode, count]) => (
              <span key={mode} className="inline-flex items-center gap-1">
                {count} <ModeBadge mode={mode as "REAL" | "SIMULATED"} compact />
              </span>
            ))}
          </span>,
        ],
        [
          "Suppliers",
          <span key="suppliers" className="inline-flex flex-wrap items-center gap-1.5">
            {Object.entries(state.modes.suppliers).map(([mode, count]) => (
              <span key={mode} className="inline-flex items-center gap-1">
                {count} <ModeBadge mode={mode as "REAL" | "SIMULATED"} compact />
              </span>
            ))}
          </span>,
        ],
        [
          "Agents' language",
          state.llm.model
            ? `${state.llm.provider} · ${state.llm.model}`
            : "Offline templates (no API key)",
        ],
        ["Telegram", state.telegram ? "Bot connected" : "Off (no bot token)"],
        ["Mode", state.demo_mode ? "Demo (Swarm Clock)" : "Production (real clock)"],
      ]
    : [];
  return (
    <Card>
      <CardHeader title="Running with" subtitle="What this server is configured to use" />
      <dl className="divide-line divide-y px-5 pb-3 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 py-2">
            <dt className="text-ink-2">{label}</dt>
            <dd className="text-ink text-right">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function ActivityLog({ state }: { state?: DemoState }) {
  return (
    <Card>
      <CardHeader title="Panel log" subtitle="The last things pressed and run" />
      <ol
        className="feed max-h-72 space-y-1.5 overflow-y-auto px-5 pb-4 text-xs"
        tabIndex={0}
        aria-label="Panel log"
      >
        {(state?.log ?? []).map((entry, index) => (
          <li key={`${entry.at}-${index}`} className="flex gap-2">
            <span className="tabular text-muted shrink-0">{dayTime(entry.at)}</span>
            <span className="text-ink">{humanize(entry.action.replace("inject:", "inject "))}</span>
            {typeof entry.details.step === "string" ? (
              <span className="text-ink-2">{humanize(entry.details.step)}</span>
            ) : null}
          </li>
        ))}
        {state && state.log.length === 0 ? <li className="text-muted">Nothing yet.</li> : null}
      </ol>
    </Card>
  );
}
