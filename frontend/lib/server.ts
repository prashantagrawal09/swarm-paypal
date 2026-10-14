/** Server-side lookups for page metadata (titles). Never throws: falls back to the code. */

import { API_URL } from "@/lib/api";
import { CATEGORY_LABEL, shortDate } from "@/lib/format";

export async function entityName(path: string, fallback: string): Promise<string> {
  try {
    // A sleeping or slow API must not hold the page up for the sake of its title.
    const response = await fetch(`${API_URL}${path}`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return fallback;
    const body = (await response.json()) as { name?: string };
    return body.name ?? fallback;
  } catch {
    return fallback;
  }
}

export function titleFromCode(code: string): string {
  return code.replaceAll("-", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** "Dairy & eggs, week of 12 Oct" for a group order, or the fallback. */
export async function groupOrderTitle(id: string, fallback: string): Promise<string> {
  try {
    const response = await fetch(`${API_URL}/api/group-orders/${encodeURIComponent(id)}`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return fallback;
    const body = (await response.json()) as { category?: string; week?: string };
    if (!body.category) return fallback;
    const label = CATEGORY_LABEL[body.category] ?? body.category;
    return body.week ? `${label}, week of ${shortDate(`${body.week}T00:00:00+08:00`)}` : label;
  } catch {
    return fallback;
  }
}
