import type { Metadata } from "next";

import { ShopStatement } from "@/components/shop-statement";
import { entityName, titleFromCode } from "@/lib/server";

export async function generateMetadata({
  params,
}: PageProps<"/shop/[id]/statement">): Promise<Metadata> {
  const { id } = await params;
  const name = await entityName(`/api/shops/${id}`, titleFromCode(id));
  return { title: `${name}: weekly statement` };
}

export default async function StatementPage({ params }: PageProps<"/shop/[id]/statement">) {
  const { id } = await params;
  return <ShopStatement code={id} />;
}
