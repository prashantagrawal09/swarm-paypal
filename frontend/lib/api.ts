/** Thin helpers for talking to the Swarm FastAPI backend. */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Health = {
  status: string;
  version: string;
  env: string;
  database: "ok" | "unavailable";
};

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch(`${API_URL}/health`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
  return (await response.json()) as Health;
}
