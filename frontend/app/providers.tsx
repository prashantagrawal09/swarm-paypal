"use client";

import { SWRConfig } from "swr";

import { fetcher } from "@/lib/api";
import { LiveProvider } from "@/lib/live";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        fetcher,
        revalidateOnFocus: true,
        keepPreviousData: true,
        errorRetryCount: 3,
        dedupingInterval: 800,
      }}
    >
      <LiveProvider>{children}</LiveProvider>
    </SWRConfig>
  );
}
