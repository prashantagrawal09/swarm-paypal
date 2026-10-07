"use client";

import { useEffect } from "react";

import { Button, ButtonLink } from "@/components/ui";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-24">
      <div className="max-w-md text-center">
        <h1 className="text-ink text-xl font-semibold">Something went wrong</h1>
        <p className="text-ink-2 mt-1 text-sm">
          This page hit an error. The agents and the money are fine: everything runs on the server.
        </p>
        {error.digest ? (
          <p className="text-muted mt-2 font-mono text-xs">Reference {error.digest}</p>
        ) : null}
        <div className="mt-6 flex justify-center gap-2">
          <Button variant="primary" onClick={reset}>
            Try again
          </Button>
          <ButtonLink href="/">Home</ButtonLink>
        </div>
      </div>
    </div>
  );
}
