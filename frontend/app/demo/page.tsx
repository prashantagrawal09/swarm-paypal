import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Demo panel" };

export default function DemoPanelPage() {
  return (
    <ComingSoon
      title="Demo control panel"
      summary="Advance the Swarm Clock day by day, run a full week, and inject short deliveries, wrong invoices, surplus offers and emergencies."
      phase={5}
    />
  );
}
