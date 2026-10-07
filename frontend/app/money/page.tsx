import type { Metadata } from "next";

import { MoneyView } from "@/components/money-view";

export const metadata: Metadata = { title: "Money" };

export default function MoneyPage() {
  return <MoneyView />;
}
