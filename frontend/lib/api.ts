/** Typed client for the Swarm FastAPI backend. */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export type Mode = "REAL" | "SIMULATED";

export type Health = {
  status: string;
  version: string;
  env: string;
  database: "ok" | "unavailable";
};

export type Step = {
  key: string;
  title: string;
  description: string;
  at: string;
  status: "done" | "next" | "pending";
};

export type Stats = {
  saved_cents: number;
  negotiation_saved_cents: number;
  food_saved_grams: number;
  captured_cents: number;
  payouts_cents: number;
  refunds_cents: number;
  holds_outstanding_cents: number;
  fees_cents: number;
  paypal_calls: Record<Mode, number>;
  books_balanced: boolean;
  shops: number;
  delivered_lines: number;
};

export type DemoState = {
  now: string;
  local: string;
  day: string;
  phase: string;
  week: string;
  steps: Step[];
  running: boolean;
  scenario: Record<string, Record<string, unknown>>;
  modes: { shops: Partial<Record<Mode, number>>; suppliers: Partial<Record<Mode, number>> };
  llm: { provider: string; model: string | null };
  paypal_env: string;
  telegram: boolean;
  demo_mode: boolean;
  log: { action: string; actor: string; at: string; details: Record<string, unknown> }[];
};

export type Overview = DemoState & { stats: Stats };

export type ShopSummary = {
  code: string;
  name: string;
  owner: string;
  kind: string;
  address: string;
  lat: number;
  lng: number;
  mode: Mode;
  connected: boolean;
  limit_cents: number;
  hours: Record<string, string>;
  committed_cents: number;
  saved_week_cents: number;
  orders: { category: string; status: string }[];
  pending_approvals: number;
};

export type WeekReport = {
  shop: string;
  week: string;
  groups: {
    category: string;
    supplier: string;
    paid_cents: number;
    alone_cents: number;
    saved_cents: number;
  }[];
  group_saved_cents: number;
  swap_income_cents: number;
  help_income_cents: number;
  swap_spent_cents: number;
  swap_saved_cents: number;
  flash_saved_cents: number;
  food_saved_grams: number;
  refunds_cents: number;
  total_saved_cents: number;
};

export type ShopDetail = Omit<ShopSummary, "orders" | "saved_week_cents" | "pending_approvals"> & {
  report: WeekReport;
  saved_to_date_cents: number;
  usual_weekly: Record<string, number>;
  accepted_brands: Record<string, string[]>;
  allow_substitutes: boolean;
  telegram_linked: boolean;
  approvals: { id: string; kind: string; status: string; question: string; at: string }[];
  forecast: {
    week: string;
    note: string;
    items: {
      product: string;
      name: string;
      unit: string;
      predicted: number;
      confirmed: number | null;
      status: string | null;
      explanation: string;
    }[];
  };
};

export type Tier = { min_qty: number; unit_price_cents: number };

export type LadderEntry = {
  product: string;
  name: string;
  unit: string;
  units: string;
  qty: number;
  tiers: Tier[];
  tier_price_cents: number | null;
  single_price_cents: number | null;
  agreed_cents: number | null;
  supplier: string | null;
};

export type GroupOrder = {
  id: string;
  week: string;
  category: string;
  status: string;
  rounds: number;
  supplier: { code: string; name: string } | null;
  shops: number;
  pooled: Record<string, number>;
  pooled_text: string;
  list_landed_cents: number | null;
  opening_landed_cents: number | null;
  final_landed_cents: number | null;
  alone_cents: number;
  paid_cents: number;
  saved_cents: number;
  excluded: { shop: string; product: string; brand: string; reason: string }[];
  conversation_id: string | null;
  delivery_fee_cents: number;
  quotes: {
    supplier: string;
    supplier_name: string;
    round: number;
    landed_cents: number;
    status: string;
  }[];
  ladder: LadderEntry[];
  payouts: { sequence: number; gross_cents: number; fee_cents: number; net_cents: number }[];
};

export type AgentMessage = {
  id: string;
  seq: number;
  conversation_id: string;
  from: string;
  to: string;
  type: string;
  text: string;
  payload: Record<string, unknown> & {
    actions?: { id: string; label: string; style?: string }[];
    answered?: string;
  };
  at: string;
};

export type PaymentRow = {
  id: string;
  kind: string;
  status: string;
  mode: Mode;
  amount_cents: number;
  currency: string;
  paypal_id: string | null;
  related_type: string;
  related_id: string;
  shop: { code: string; name: string } | null;
  supplier: { code: string; name: string } | null;
  error: string | null;
  at: string;
};

export type SupplierSummary = {
  code: string;
  name: string;
  mode: Mode;
  reliability: number;
  delivery_fee_cents: number;
  delivery_days: string[];
  tagline: string;
  style: string;
  platform_fee_bps: number;
  awards?: number;
  paid_out_cents?: number;
};

export type SupplierDetail = SupplierSummary & {
  catalog: {
    sku: string;
    product: string;
    name: string;
    brand: string;
    category: string;
    unit: string;
    tiers: Tier[];
    stock: number;
  }[];
};

export type InvoiceRow = {
  id: string;
  number: string;
  revision: number;
  paypal_invoice_id: string | null;
  total_cents: number;
  check_status: "PENDING" | "APPROVED" | "REJECTED";
  report: {
    approved?: boolean;
    summary?: string;
    issues?: { kind: string; text: string }[];
    expected_total_cents?: number;
    invoiced_total_cents?: number;
    overcharge_cents?: number;
  };
  lines: {
    product: string;
    name: string;
    qty: number;
    unit_price_cents: number;
    total_cents: number;
  }[];
  paypal_status: string | null;
  mode: Mode;
  issued_via: string | null;
  paid: boolean;
  group_order_id: string;
  supplier: { code: string; name: string } | null;
  at: string;
};

export type SwapRow = {
  id: string;
  kind: "SURPLUS" | "EMERGENCY";
  status: string;
  role: "seller" | "buyer" | null;
  seller: { code: string; name: string } | null;
  buyer: { code: string; name: string } | null;
  product: string;
  product_name: string;
  unit: string;
  qty: number;
  price_cents: number;
  food_saved_grams: number;
  discount_pct: number | null;
  seconds_to_sorted: number | null;
  at: string;
};

export type ClaimRow = {
  id: string;
  type: string;
  qty: number;
  amount_cents: number;
  decision: string;
  description: string | null;
  photo_url: string | null;
  assessment: Record<string, unknown>;
  note: string | null;
  at: string;
  shop?: { code: string; name: string } | null;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function fetcher<T>(path: string): Promise<T> {
  const headers: Record<string, string> = {};
  const key = path.startsWith("/api/owners/") ? demoKey() : null;
  if (key) headers["X-Demo-Key"] = key;
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", headers });
  if (!response.ok) {
    throw new ApiError(response.status, await errorText(response));
  }
  return (await response.json()) as T;
}

async function errorText(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : response.statusText;
  } catch {
    return response.statusText;
  }
}

const DEMO_KEY = "swarm-demo-key";
let keyInMemory: string | null = null;

/** The key from a shared link's fragment ("#key=...") if there is one. */
export function keyFromHash(hash: string): string | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get("key");
  return value ? value.trim() || null : null;
}

/**
 * A link can carry the demo key in its fragment (".../live?play=1#key=..."), which
 * browsers never send to a server. It is saved on first use and removed from the address.
 */
function adoptKeyFromLink(): void {
  if (typeof window === "undefined" || !window.location.hash.includes("key=")) return;
  const key = keyFromHash(window.location.hash);
  if (!key) return;
  setDemoKey(key);
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

export function demoKey(): string | null {
  adoptKeyFromLink();
  try {
    return localStorage.getItem(DEMO_KEY) ?? keyInMemory;
  } catch {
    return keyInMemory;
  }
}

export function setDemoKey(value: string): void {
  keyInMemory = value;
  try {
    localStorage.setItem(DEMO_KEY, value);
  } catch {
    /* private mode: the key only lives for this page */
  }
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = demoKey();
  if (key) headers["X-Demo-Key"] = key;
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorText(response));
  }
  return (await response.json()) as T;
}

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const key = demoKey();
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: form,
    headers: key ? { "X-Demo-Key": key } : undefined,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorText(response));
  }
  return (await response.json()) as T;
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch(`${API_URL}/health`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
  return (await response.json()) as Health;
}

export function mediaUrl(path: string | null): string | null {
  return path ? `${API_URL}${path}` : null;
}

export type FlashDeal = {
  id: string;
  supplier: { code: string; name: string };
  item: string;
  brand: string;
  unit: string;
  qty: number;
  taken: number;
  price_cents: number;
  list_price_cents: number;
  discount_pct: number | null;
  status: string;
  expires_at: string | null;
  purchases: { shop: string; qty: number; amount_cents: number }[];
};

export type Ledger = {
  balances: {
    platform: Record<string, number>;
    suppliers: Record<string, number>;
    shops: Record<string, number>;
  };
  invariant_gap_cents: number;
  unbalanced_transactions: number;
  entries: number;
};

export type ShopOrderLine = {
  id: string;
  week: string;
  category: string;
  supplier: string | null;
  item: string;
  brand: string;
  product: string;
  unit: string;
  qty_requested: number;
  qty_delivered: number | null;
  unit_price_cents: number | null;
  alone_unit_price_cents: number | null;
  line_total_cents: number;
  order_status: string;
  group_status: string;
  hold_cents: number;
  captured_cents: number;
  refunded_cents: number;
  delivery_share_cents: number;
  shop_order_id: string;
};

export type QuoteRow = {
  id: string;
  week: string;
  category: string;
  round: number;
  items_total_cents: number;
  delivery_fee_cents: number;
  landed_total_cents: number;
  status: string;
  message: string | null;
  unit_prices: Record<string, number>;
  group_order_id: string;
};

export type GroupOrderDetail = GroupOrder & {
  shop_orders: {
    shop: { code: string; name: string; mode: Mode };
    status: string;
    hold_cents: number;
    captured_cents: number;
    refunded_cents: number;
    delivery_share_cents: number;
    authorization_id: string | null;
    capture_id: string | null;
    failure_reason: string | null;
    lines: {
      item: string;
      brand: string;
      product: string;
      qty_requested: number;
      qty_delivered: number | null;
      unit_price_cents: number | null;
    }[];
  }[];
  invoices: InvoiceRow[];
};

export type Product = {
  product: string;
  name: string;
  unit: string;
  units: string;
  category: string;
  skus: { sku: string; brand: string; name: string; supplier: string }[];
};

export type MoneyFlow = {
  week: string;
  charged_cents: number;
  suppliers_cents: number;
  neighbours_cents: number;
  refunds_cents: number;
  fee_cents: number;
  owed_cents: number;
  held_cents: number;
  shops: {
    code: string;
    name: string;
    mode: Mode;
    charged_cents: number;
    refunded_cents: number;
    received_cents: number;
  }[];
  suppliers: { code: string; name: string; mode: Mode; paid_cents: number }[];
};
