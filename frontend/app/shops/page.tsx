import type { Metadata } from "next";

import { ShopDirectory } from "@/components/directories";

export const metadata: Metadata = { title: "Shops" };

export default function ShopsPage() {
  return <ShopDirectory />;
}
