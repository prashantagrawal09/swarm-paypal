import type { Metadata } from "next";

import { ConnectFlow } from "@/components/connect-flow";

export const metadata: Metadata = { title: "Connect PayPal", robots: { index: false } };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ConnectPage({
  params,
  searchParams,
}: PageProps<"/connect/[shopId]">) {
  const { shopId } = await params;
  const query = await searchParams;
  return (
    <ConnectFlow
      // A new approval (fresh query) starts the flow over.
      key={JSON.stringify(query)}
      code={shopId}
      params={{
        t: first(query.t),
        sim_order: first(query.sim_order),
        token: first(query.token),
        cancelled: first(query.cancelled),
      }}
    />
  );
}
