import type { Metadata } from "next";

import { SupplierView } from "@/components/supplier-view";
import { entityName, titleFromCode } from "@/lib/server";

export async function generateMetadata({ params }: PageProps<"/supplier/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: await entityName(`/api/suppliers/${id}`, titleFromCode(id)) };
}

export default async function SupplierPage({ params }: PageProps<"/supplier/[id]">) {
  const { id } = await params;
  return <SupplierView code={id} />;
}
