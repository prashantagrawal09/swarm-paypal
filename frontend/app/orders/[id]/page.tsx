import type { Metadata } from "next";

import { OrderView } from "@/components/order-view";

export const metadata: Metadata = { title: "Group order" };

export default async function OrderPage({ params }: PageProps<"/orders/[id]">) {
  const { id } = await params;
  return <OrderView id={id} />;
}
