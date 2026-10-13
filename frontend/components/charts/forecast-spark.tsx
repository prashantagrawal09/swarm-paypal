/**
 * The weeks a forecast is based on (grey bars) and the forecast itself (the dark bar), small
 * enough to sit in a table row. One series, so no legend; the caller explains the two tones
 * once for the whole list, and the numbers are in the label for screen readers.
 */

const BAR = 7;
const GAP = 3;
const H = 22;

export function ForecastSpark({
  history,
  forecast,
  unit,
}: {
  history: number[];
  forecast: number;
  unit: string;
}) {
  if (history.length === 0) return null;
  const values = [...history, forecast];
  const top = Math.max(1, ...values);
  const width = values.length * BAR + (values.length - 1) * GAP;
  return (
    <svg
      width={width}
      height={H}
      viewBox={`0 0 ${width} ${H}`}
      className="shrink-0"
      role="img"
      aria-label={`Last ${history.length} weeks: ${history.join(", ")} ${unit}. Forecast: ${forecast}.`}
    >
      {values.map((value, index) => {
        const height = Math.max(2, (value / top) * (H - 1));
        const isForecast = index === values.length - 1;
        return (
          <rect
            key={index}
            x={index * (BAR + GAP)}
            y={H - height}
            width={BAR}
            height={height}
            rx={2}
            fill={isForecast ? "var(--ink)" : "var(--muted)"}
          />
        );
      })}
    </svg>
  );
}
