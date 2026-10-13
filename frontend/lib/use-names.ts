"use client";

import { useMemo } from "react";
import useSWR from "swr";

import type { ShopSummary, SupplierSummary } from "@/lib/api";

/** id -> display name for every shop and supplier. */
export function useNames(): Record<string, string> {
  const { data: shops } = useSWR<ShopSummary[]>("/api/shops");
  const { data: suppliers } = useSWR<SupplierSummary[]>("/api/suppliers");
  return useMemo(() => {
    const names: Record<string, string> = {};
    for (const shop of shops ?? []) names[shop.code] = shop.name;
    for (const supplier of suppliers ?? []) names[supplier.code] = supplier.name;
    return names;
  }, [shops, suppliers]);
}
