import type { Metadata } from "next";

import { ShopView } from "@/components/shop-view";
import { entityName, titleFromCode } from "@/lib/server";

export async function generateMetadata({ params }: PageProps<"/shop/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: await entityName(`/api/shops/${id}`, titleFromCode(id)) };
}

export default async function ShopPage({ params }: PageProps<"/shop/[id]">) {
  const { id } = await params;
  return <ShopView code={id} />;
}
