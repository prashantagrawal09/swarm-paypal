/** Placeholder body for screens that are scheduled for a later build phase. */

export function ComingSoon({
  title,
  summary,
  phase,
}: {
  title: string;
  summary: string;
  phase: number;
}) {
  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 max-w-2xl text-stone-600 dark:text-stone-400">{summary}</p>
      <div className="mt-8 rounded-xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500 dark:border-stone-700">
        This screen is built in phase {phase}.
      </div>
    </section>
  );
}
