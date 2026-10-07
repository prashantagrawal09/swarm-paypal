import type { Metadata } from "next";

import { SupplierDirectory } from "@/components/directories";

export const metadata: Metadata = { title: "Suppliers" };

export default function SuppliersPage() {
  return <SupplierDirectory />;
}
