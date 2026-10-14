/** Small, shared UI building blocks. */

import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock3,
  Loader2,
  type LucideIcon,
  PauseCircle,
  XCircle,
} from "lucide-react";
import Link from "next/link";

import type { Mode } from "@/lib/api";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
  id,
  as: Tag = "section",
}: {
  children?: React.ReactNode;
  className?: string;
  /** For a link that lands on this card. */
  id?: string;
  as?: "section" | "div" | "article";
}) {
  return (
    <Tag
      id={id}
      className={cx("border-line bg-surface rounded-2xl border shadow-[var(--shadow)]", className)}
    >
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon: Icon,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  icon?: LucideIcon;
}) {
  return (
    // Where the title and its action don't both fit (a phone), the action moves underneath.
    <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-5 pt-4 pb-3">
      <div className="min-w-0 flex-1 basis-56">
        <h2 className="text-ink flex items-center gap-2 text-sm font-semibold tracking-tight">
          {Icon ? <Icon className="text-muted h-4 w-4" aria-hidden /> : null}
          {title}
        </h2>
        {subtitle ? <p className="text-ink-2 mt-0.5 text-xs">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

export function ModeBadge({ mode, compact = false }: { mode: Mode; compact?: boolean }) {
  const real = mode === "REAL";
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        real ? "bg-real-soft text-real" : "bg-surface-2 text-ink-2",
      )}
      title={real ? "Real PayPal sandbox API calls" : "Simulated PayPal (same rules, no network)"}
    >
      <span className={cx("h-1.5 w-1.5 rounded-full", real ? "bg-real" : "bg-muted")} aria-hidden />
      {real ? (compact ? "REAL" : "REAL sandbox") : compact ? "SIM" : "Simulated"}
    </span>
  );
}

type Tone = "good" | "warning" | "critical" | "info" | "neutral" | "busy";

const TONES: Record<Tone, { className: string; icon: LucideIcon }> = {
  good: { className: "bg-good-soft text-good-ink", icon: CheckCircle2 },
  warning: { className: "bg-warning-soft text-warning-ink", icon: PauseCircle },
  critical: { className: "bg-critical-soft text-critical-ink", icon: XCircle },
  info: { className: "bg-real-soft text-real", icon: Clock3 },
  neutral: { className: "bg-surface-2 text-ink-2", icon: Circle },
  busy: { className: "bg-honey-soft text-honey-ink", icon: Loader2 },
};

/** Status chips always pair the colour with an icon and a word. */
export function StatusPill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const { className, icon: Icon } = TONES[tone];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        className,
      )}
    >
      <Icon className={cx("h-3 w-3", tone === "busy" && "animate-spin")} aria-hidden />
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  PENDING: "neutral",
  AUTHORIZED: "info",
  CAPTURED: "good",
  SETTLED: "good",
  VOIDED: "neutral",
  REFUNDED: "warning",
  FAILED: "critical",
  COMPLETED: "good",
  APPROVED: "good",
  REJECTED: "critical",
  COLLECTING: "neutral",
  NEGOTIATING: "busy",
  AWARDED: "info",
  HELD: "info",
  OUT_FOR_DELIVERY: "busy",
  DELIVERED: "good",
  PARTIALLY_SETTLED: "warning",
  CANCELLED: "neutral",
  OPEN: "busy",
  ACCEPTED: "info",
  PAID: "good",
  EXPIRED: "neutral",
  AUTO_REFUNDED: "good",
  ESCALATED_SUPPLIER: "warning",
  ESCALATED_OPERATOR: "warning",
  SOLD_OUT: "good",
  DRAFT: "neutral",
  SUBMITTED: "neutral",
  DECLINED: "neutral",
  SUPERSEDED: "neutral",
  FINAL: "info",
  LOST: "neutral",
};

const STATUS_WORD: Record<string, string> = {
  AUTHORIZED: "Held",
  CAPTURED: "Charged",
  OUT_FOR_DELIVERY: "On the way",
  HELD: "Holds placed",
  PARTIALLY_SETTLED: "Part settled",
  ESCALATED_SUPPLIER: "With supplier",
  ESCALATED_OPERATOR: "With operator",
  AUTO_REFUNDED: "Refunded",
  LOST: "Not chosen",
  SUPERSEDED: "Revised",
  SOLD_OUT: "Sold out",
};

export function Status({ value, word: override }: { value: string; word?: string }) {
  const word =
    override ??
    STATUS_WORD[value] ??
    value.charAt(0) + value.slice(1).toLowerCase().replaceAll("_", " ");
  return <StatusPill tone={STATUS_TONE[value] ?? "neutral"}>{word}</StatusPill>;
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled,
  busy,
  className,
  type = "button",
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger" | "honey";
  disabled?: boolean;
  busy?: boolean;
  className?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  const styles = {
    primary: "bg-ink text-page hover:opacity-90",
    honey: "bg-honey text-[#1c1400] hover:brightness-105",
    secondary: "border border-line-strong bg-surface text-ink hover:bg-surface-2",
    ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
    danger: "border border-line-strong bg-surface text-critical-ink hover:bg-critical-soft",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      title={title}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        styles,
        className,
      )}
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  children,
  variant = "secondary",
  className,
}: {
  href: string;
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "honey";
  className?: string;
}) {
  const styles = {
    primary: "bg-ink text-page hover:opacity-90",
    honey: "bg-honey text-[#1c1400] hover:brightness-105",
    secondary: "border border-line-strong bg-surface text-ink hover:bg-surface-2",
  }[variant];
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition",
        styles,
        className,
      )}
    >
      {children}
    </Link>
  );
}

/** A ratio against a limit: fill in the accent; amber then red as it nears and passes 100%. */
export function Meter({ value, max, label }: { value: number; max: number; label?: string }) {
  const ratio = max > 0 ? value / max : 0;
  const pct = Math.min(100, Math.round(ratio * 100));
  const fill = ratio > 1 ? "bg-critical" : ratio > 0.85 ? "bg-warning" : "bg-s1";
  return (
    <div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--s1-soft)]"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className={cx("h-full rounded-full transition-all", fill)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-line-strong text-muted grid place-items-center rounded-xl border border-dashed px-6 py-10 text-center text-sm">
      {children}
    </div>
  );
}

export function Warning({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-line bg-warning-soft text-warning-ink flex items-start gap-2 rounded-xl border px-3 py-2 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M16 2.5 28 9.25v13.5L16 29.5 4 22.75V9.25Z" fill="var(--honey)" />
      <path
        d="M16 9.5 21.6 12.7v6.6L16 22.5l-5.6-3.2v-6.6Z"
        fill="none"
        stroke="#1c1400"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="16" r="1.9" fill="#1c1400" />
    </svg>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="border-line-strong bg-surface-2 text-ink-2 rounded border px-1.5 py-0.5 font-mono text-[11px]">
      {children}
    </kbd>
  );
}

export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cx("text-ink-2 font-mono text-[11px]", className)}>{children}</span>;
}

/** A page for something that isn't there: a shop, supplier or order nobody has heard of. */
export function Missing({
  title,
  children,
  href,
  action,
}: {
  title: React.ReactNode;
  children?: React.ReactNode;
  href: string;
  action: string;
}) {
  return (
    <div className="honeycomb flex flex-1 items-center justify-center px-4 py-24">
      <div className="max-w-md text-center">
        <Logo className="mx-auto h-10 w-10" />
        <h1 className="text-ink mt-4 text-xl font-semibold text-balance">{title}</h1>
        {children ? <p className="text-ink-2 mt-1 text-sm">{children}</p> : null}
        <ButtonLink href={href} variant="primary" className="mt-6">
          {action}
        </ButtonLink>
      </div>
    </div>
  );
}
