import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Live board" };

export default function LiveBoardPage() {
  return (
    <ComingSoon
      title="Swarm live board"
      summary="The 12 shops, this week's group orders, the price ladder, the agent conversation and PayPal events, updating in real time."
      phase={5}
    />
  );
}
