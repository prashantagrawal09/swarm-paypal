"use client";

/**
 * Connect PayPal: the owner approves a S$1.00 check once with "save PayPal for future
 * purchases"; Swarm keeps the vault reference and releases the S$1.00 straight away.
 *
 * REAL shops go to PayPal and come back here with `?token=<order id>`. Simulated shops get
 * an approval screen right here, clearly labelled as the simulator.
 */

import {
  ArrowRight,
  CheckCircle2,
  FlaskConical,
  Hand,
  Lock,
  RotateCcw,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";

import { Button, ButtonLink, Card, ModeBadge, Skeleton, Warning } from "@/components/ui";
import { ApiError, post, type ShopDetail } from "@/lib/api";
import { moneyWhole } from "@/lib/format";

type Params = { t?: string; sim_order?: string; token?: string; cancelled?: string };
type Phase =
  | { kind: "intro" }
  | { kind: "simulated"; orderId: string }
  | { kind: "finishing" }
  | { kind: "done"; vaultTail: string; email: string | null }
  | { kind: "cancelled" }
  | { kind: "error"; message: string };

function initialPhase(params: Params): Phase {
  if (params.cancelled) return { kind: "cancelled" };
  if (params.sim_order) return { kind: "simulated", orderId: params.sim_order };
  if (params.token) return { kind: "finishing" };
  return { kind: "intro" };
}

export function ConnectFlow({ code, params }: { code: string; params: Params }) {
  const { data: shop, error: shopError } = useSWR<ShopDetail>(`/api/shops/${code}`);
  const [phase, setPhase] = useState<Phase>(() => initialPhase(params));
  const [busy, setBusy] = useState(false);
  const finished = useRef(false);
  const link = params.t ?? null;

  async function complete(orderId: string) {
    setPhase({ kind: "finishing" });
    try {
      const result = await post<{
        connected: boolean;
        vault_tail: string;
        payer_email: string | null;
      }>(`/api/connect/${code}/complete`, { order_id: orderId, token: link });
      setPhase({ kind: "done", vaultTail: result.vault_tail, email: result.payer_email });
    } catch (err) {
      setPhase({
        kind: "error",
        message: err instanceof Error ? err.message : "Couldn't finish connecting.",
      });
    }
  }

  // Back from PayPal with the approved order: finish exactly once.
  useEffect(() => {
    if (params.token && !finished.current) {
      finished.current = true;
      void complete(params.token);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.token]);

  async function start() {
    setBusy(true);
    try {
      const result = await post<{ approve_url: string; order_id: string; mode: string }>(
        `/api/connect/${code}/start`,
        { token: link },
      );
      window.location.assign(result.approve_url);
    } catch (err) {
      setBusy(false);
      const message =
        err instanceof ApiError && err.status === 403
          ? `${err.message} Ask the Swarm bot for a fresh link with /connect.`
          : err instanceof Error
            ? err.message
            : "Couldn't reach PayPal.";
      setPhase({ kind: "error", message });
    }
  }

  async function approveSimulated(orderId: string) {
    setBusy(true);
    try {
      await post(`/api/connect/${code}/simulated-approve`, { order_id: orderId, token: link });
      await complete(orderId);
    } catch (err) {
      setPhase({ kind: "error", message: err instanceof Error ? err.message : "Approval failed." });
    } finally {
      setBusy(false);
    }
  }

  const retry = `/connect/${code}${link ? `?t=${encodeURIComponent(link)}` : ""}`;

  return (
    <div className="honeycomb flex flex-1 items-start justify-center px-4 py-10 sm:py-16">
      <Card className="w-full max-w-md overflow-hidden">
        <div className="border-line bg-surface-2 border-b px-6 py-4">
          <div className="text-ink-2 text-xs">Connect PayPal for</div>
          <div className="mt-0.5 flex items-center gap-2">
            <h1 className="text-ink text-lg font-semibold">
              {shop?.name ?? (shopError ? code : <Skeleton className="h-5 w-32" />)}
            </h1>
            {shop ? <ModeBadge mode={shop.mode} compact /> : null}
          </div>
        </div>

        <div className="px-6 py-6">
          {phase.kind === "intro" ? (
            <>
              {shop?.connected ? (
                <div className="bg-good-soft text-good-ink mb-4 flex items-center gap-2 rounded-xl px-3 py-2 text-sm">
                  <CheckCircle2 className="h-4 w-4" aria-hidden /> Already connected. You can
                  reconnect to switch accounts.
                </div>
              ) : null}
              <p className="text-ink-2 text-sm">
                Approve once, and your Swarm agent can hold money for group orders without asking
                you to log in each week.
              </p>
              <ul className="mt-5 space-y-3 text-sm">
                {[
                  {
                    icon: Wallet,
                    text: "PayPal asks you to approve a S$1.00 check. Swarm releases it straight away, so nothing is charged.",
                  },
                  {
                    icon: Hand,
                    text: `Each week the agent places a hold for your share of the group order, within your weekly limit${shop ? ` of ${moneyWhole(shop.limit_cents)}` : ""}. Above it, the agent asks you first.`,
                  },
                  {
                    icon: ShieldCheck,
                    text: "You're only charged for what was delivered. Short deliveries cost less, automatically.",
                  },
                  { icon: Lock, text: "You can remove Swarm any time from your PayPal settings." },
                ].map(({ icon: Icon, text }) => (
                  <li key={text} className="flex gap-3">
                    <span
                      className="bg-honey-soft text-honey-ink grid h-7 w-7 shrink-0 place-items-center rounded-lg"
                      aria-hidden
                    >
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <span className="text-ink-2">{text}</span>
                  </li>
                ))}
              </ul>
              <Button
                variant="primary"
                className="mt-6 w-full"
                busy={busy}
                onClick={start}
                disabled={!shop}
              >
                {shop?.mode === "SIMULATED"
                  ? "Continue to the simulated approval"
                  : "Continue to PayPal"}
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Button>
            </>
          ) : null}

          {phase.kind === "simulated" ? (
            <div>
              <div className="bg-surface-2 text-ink-2 flex items-center gap-2 rounded-xl px-3 py-2 text-xs">
                <FlaskConical className="h-4 w-4 shrink-0" aria-hidden />
                Simulator: this shop uses simulated PayPal, so no real account is involved. A REAL
                shop sees PayPal&apos;s own approval page here.
              </div>
              <dl className="mt-5 space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-ink-2">Merchant</dt>
                  <dd className="text-ink font-medium">Swarm</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-2">Amount</dt>
                  <dd className="tabular text-ink font-medium">S$1.00, released straight away</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-2">Save for future purchases</dt>
                  <dd className="text-ink font-medium">Yes</dd>
                </div>
              </dl>
              <div className="mt-6 grid grid-cols-2 gap-2">
                <ButtonLink
                  href={`/connect/${code}?cancelled=1${link ? `&t=${encodeURIComponent(link)}` : ""}`}
                >
                  Cancel
                </ButtonLink>
                <Button variant="honey" busy={busy} onClick={() => approveSimulated(phase.orderId)}>
                  Approve
                </Button>
              </div>
            </div>
          ) : null}

          {phase.kind === "finishing" ? (
            <div className="text-ink-2 py-6 text-center text-sm">
              <div
                className="border-line border-t-honey mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2"
                aria-hidden
              />
              Saving your PayPal and releasing the S$1.00 check...
            </div>
          ) : null}

          {phase.kind === "done" ? (
            <div className="text-center">
              <CheckCircle2 className="text-good-ink mx-auto h-10 w-10" aria-hidden />
              <h2 className="text-ink mt-3 text-lg font-semibold">PayPal connected</h2>
              <p className="text-ink-2 mt-1 text-sm">
                {phase.email ? `${phase.email} is saved` : "Your PayPal is saved"} (reference …
                {phase.vaultTail}). The S$1.00 check was released. Your agent will message you on
                Monday with the coming week&apos;s order.
              </p>
              <ButtonLink href={`/shop/${code}`} variant="primary" className="mt-5">
                See {shop?.name ?? "the shop"}
              </ButtonLink>
            </div>
          ) : null}

          {phase.kind === "cancelled" ? (
            <div className="text-center">
              <p className="text-ink-2 text-sm">
                You cancelled, so nothing changed and nothing was charged.
              </p>
              <ButtonLink href={retry} variant="primary" className="mt-5">
                <RotateCcw className="h-4 w-4" aria-hidden /> Try again
              </ButtonLink>
            </div>
          ) : null}

          {phase.kind === "error" ? (
            <div>
              <Warning>{phase.message}</Warning>
              <div className="mt-4 flex gap-2">
                <ButtonLink href={retry}>Start again</ButtonLink>
                <Link
                  href={`/shop/${code}`}
                  className="text-ink-2 hover:text-ink px-3 py-2 text-sm"
                >
                  Back to the shop
                </Link>
              </div>
            </div>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
