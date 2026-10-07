/** Formatting helpers: money in cents, times in Singapore, names for agents and products. */

const SGD = new Intl.NumberFormat("en-SG", {
  style: "currency",
  currency: "SGD",
  currencyDisplay: "narrowSymbol",
  minimumFractionDigits: 2,
});

const SGD_WHOLE = new Intl.NumberFormat("en-SG", {
  style: "currency",
  currency: "SGD",
  currencyDisplay: "narrowSymbol",
  maximumFractionDigits: 0,
});

/** 123456 -> "S$1,234.56" */
export function money(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "-";
  const sign = cents < 0 ? "-" : "";
  return `${sign}S${SGD.format(Math.abs(cents) / 100)}`;
}

/** Whole dollars for big headline numbers: 232700 -> "S$2,327" */
export function moneyWhole(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}S${SGD_WHOLE.format(Math.round(Math.abs(cents) / 100))}`;
}

/** 12900 -> "12.9K"-style compact for tiles. */
export function compact(value: number): string {
  return new Intl.NumberFormat("en-SG", { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

export function kg(grams: number): string {
  return `${(grams / 1000).toFixed(1)} kg`;
}

const TIME = new Intl.DateTimeFormat("en-SG", {
  timeZone: "Asia/Singapore",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DAY_TIME = new Intl.DateTimeFormat("en-SG", {
  timeZone: "Asia/Singapore",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE = new Intl.DateTimeFormat("en-SG", {
  timeZone: "Asia/Singapore",
  day: "numeric",
  month: "short",
});

export function time(iso: string): string {
  return TIME.format(new Date(iso));
}

export function dayTime(iso: string): string {
  return DAY_TIME.format(new Date(iso));
}

export function shortDate(iso: string): string {
  return DATE.format(new Date(iso));
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

/** "MILK-FC-1L" style enums and snake case -> "Milk fc 1l" */
export function humanize(value: string): string {
  return titleCase(value.replaceAll("_", " ").replaceAll("-", " "));
}

export const CATEGORY_LABEL: Record<string, string> = {
  DAIRY: "Dairy & eggs",
  PANTRY: "Coffee & oil",
  PRODUCE: "Fresh produce",
  PACKAGING: "Packaging",
};

export const CATEGORY_EMOJI: Record<string, string> = {
  DAIRY: "🥛",
  PANTRY: "☕",
  PRODUCE: "🥬",
  PACKAGING: "🥡",
};

/** Agent ids ("shop:cafe-mei") to display names, given the shop and supplier lists. */
export function agentName(id: string, names: Record<string, string> = {}): string {
  const [kind, code = ""] = id.split(":");
  if (kind === "coordinator") return "Swarm coordinator";
  if (kind === "claims") return "Claims agent";
  if (kind === "suppliers") return "All suppliers";
  if (kind === "shops") return "All shops";
  if (kind === "owner") return `${names[code] ?? code} (owner)`;
  return names[code] ?? code;
}

export function agentKind(id: string): "shop" | "supplier" | "coordinator" | "owner" | "other" {
  const kind = id.split(":")[0];
  if (kind === "shop" || kind === "supplier" || kind === "coordinator" || kind === "owner") {
    return kind;
  }
  return "other";
}

export function initials(name: string): string {
  const words = name
    .replace(/[^\p{L}\s&]/gu, "")
    .split(/\s+/)
    .filter(Boolean);
  return (words[0]?.[0] ?? "") + (words[1]?.[0] ?? "");
}

/** Stable supplier -> categorical slot (colour follows the entity, never its rank). */
export const SUPPLIER_SLOT: Record<string, 1 | 2 | 3> = {
  freshdairy: 1,
  johorfarm: 2,
  packpro: 3,
};

export function slotColor(code: string): string {
  return `var(--s${SUPPLIER_SLOT[code] ?? 1})`;
}
