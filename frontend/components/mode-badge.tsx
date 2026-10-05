/** Honest label for whether an account makes real PayPal sandbox calls or simulated ones. */

export type PayPalMode = "REAL" | "SIMULATED";

export function ModeBadge({ mode }: { mode: PayPalMode }) {
  const real = mode === "REAL";
  return (
    <span
      className={
        real
          ? "rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-300"
          : "rounded-full bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-600 dark:bg-stone-800 dark:text-stone-300"
      }
    >
      {real ? "REAL sandbox" : "Simulated"}
    </span>
  );
}
