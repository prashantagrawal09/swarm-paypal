"use client";

import { useEffect } from "react";
import { SWRConfig } from "swr";

import { InspectorProvider } from "@/components/message-inspector";
import { demoKey, fetcher } from "@/lib/api";
import { LiveProvider } from "@/lib/live";
import { ServerStatusProvider } from "@/lib/server-status";

export function Providers({ children }: { children: React.ReactNode }) {
  // A shared link can carry the demo key ("#key=..."); take it in as soon as the page loads.
  useEffect(() => void demoKey(), []);

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
      <ServerStatusProvider>
        <LiveProvider>
          <InspectorProvider>{children}</InspectorProvider>
        </LiveProvider>
      </ServerStatusProvider>
    </SWRConfig>
  );
}
