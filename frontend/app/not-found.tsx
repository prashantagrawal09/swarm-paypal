import type { Metadata } from "next";

import { ButtonLink, Logo } from "@/components/ui";

export const metadata: Metadata = { title: "Not found" };

export default function NotFound() {
  return (
    <div className="honeycomb flex flex-1 items-center justify-center px-4 py-24">
      <div className="text-center">
        <Logo className="mx-auto h-10 w-10" />
        <h1 className="text-ink mt-4 text-xl font-semibold">Nothing here</h1>
        <p className="text-ink-2 mt-1 text-sm">That page isn&apos;t part of the neighbourhood.</p>
        <ButtonLink href="/live" variant="primary" className="mt-6">
          Go to the live board
        </ButtonLink>
      </div>
    </div>
  );
}
