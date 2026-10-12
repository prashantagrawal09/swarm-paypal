/** Axis helpers for the charts. Pure. */

export function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min;
  if (span <= 0) return [min];
  const raw = span / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => span / s <= count + 1) ?? raw;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(Math.round(v));
  return ticks;
}

/** Drops tick labels that would sit closer than `gap` px to the previous one. */
export function thin<T extends { x: number }>(ticks: T[], gap: number): T[] {
  const kept: T[] = [];
  for (const tick of ticks) {
    if (!kept.length || tick.x - kept[kept.length - 1].x >= gap) kept.push(tick);
  }
  return kept;
}
