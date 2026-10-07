import type { Metadata } from "next";

import { DemoPanel } from "@/components/demo-panel";

export const metadata: Metadata = { title: "Demo panel" };

export default function DemoPage() {
  return <DemoPanel />;
}
