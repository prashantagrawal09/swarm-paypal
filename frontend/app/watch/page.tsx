import type { Metadata } from "next";
import { Suspense } from "react";

import { Theatre } from "@/components/theatre";

export const metadata: Metadata = {
  title: "Watch the week",
  description:
    "One week of Swarm, played back: twelve shops buy together, three suppliers compete, and PayPal holds, charges, refunds and pays.",
};

export default function WatchPage() {
  return (
    <Suspense>
      <Theatre />
    </Suspense>
  );
}
