import type { Metadata } from "next";

import { LiveBoard } from "@/components/live-board";

export const metadata: Metadata = { title: "Live board" };

export default function LivePage() {
  return <LiveBoard />;
}
