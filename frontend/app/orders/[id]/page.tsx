import type { Metadata } from "next";

import { OrderView } from "@/components/order-view";
import { groupOrderTitle } from "@/lib/server";

export async function generateMetadata({ params }: PageProps<"/orders/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: await groupOrderTitle(id, "Group order") };
}

export default async function OrderPage({ params }: PageProps<"/orders/[id]">) {
  const { id } = await params;
  return <OrderView id={id} />;
}
