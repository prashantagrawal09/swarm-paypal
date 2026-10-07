/** Server-side lookups for page metadata (titles). Never throws: falls back to the code. */

import { API_URL } from "@/lib/api";

export async function entityName(path: string, fallback: string): Promise<string> {
  try {
    const response = await fetch(`${API_URL}${path}`, { next: { revalidate: 300 } });
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
