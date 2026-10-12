"use client";

/** Shown when the server locks the demo controls (DEMO_PANEL_KEY) and this browser has no key. */

import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Button, cx } from "@/components/ui";
import { setDemoKey } from "@/lib/api";

export function DemoKeyPrompt({ onSaved, className }: { onSaved: () => void; className?: string }) {
  const [value, setValue] = useState("");
  return (
    <form
      className={cx(
        "border-line bg-warning-soft text-warning-ink flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-sm",
        className,
      )}
      onSubmit={(event) => {
        event.preventDefault();
        if (!value.trim()) return;
        setDemoKey(value.trim());
        onSaved();
      }}
    >
      <KeyRound className="h-4 w-4 shrink-0" aria-hidden />
      <span>This demo is locked. Enter the demo key to run it:</span>
      <input
        type="password"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className="border-line bg-surface text-ink h-8 min-w-32 flex-1 rounded-lg border px-2"
        aria-label="Demo key"
        autoComplete="off"
        autoFocus
      />
      <Button type="submit" variant="primary" className="h-8 py-0">
        Unlock
      </Button>
    </form>
  );
}
