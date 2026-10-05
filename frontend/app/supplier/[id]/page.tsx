import { ComingSoon } from "@/components/coming-soon";

export default async function SupplierPage({ params }: PageProps<"/supplier/[id]">) {
  const { id } = await params;
  return (
    <ComingSoon
      title={`Supplier ${id}`}
      summary="Quotes, awarded orders, invoices with their check results, and payouts for one supplier."
      phase={5}
    />
  );
}
