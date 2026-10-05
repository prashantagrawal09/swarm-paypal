import { ComingSoon } from "@/components/coming-soon";

export default async function ShopPage({ params }: PageProps<"/shop/[id]">) {
  const { id } = await params;
  return (
    <ComingSoon
      title={`Shop ${id}`}
      summary="Orders, payments, invoices, claims, swaps and the weekly savings report for one shop."
      phase={5}
    />
  );
}
