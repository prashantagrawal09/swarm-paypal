import { ComingSoon } from "@/components/coming-soon";

export default async function ConnectPage({ params }: PageProps<"/connect/[shopId]">) {
  const { shopId } = await params;
  return (
    <ComingSoon
      title={`Connect PayPal for ${shopId}`}
      summary="A one-time PayPal approval that lets this shop's agent place holds for future group orders without the owner logging in."
      phase={5}
    />
  );
}
