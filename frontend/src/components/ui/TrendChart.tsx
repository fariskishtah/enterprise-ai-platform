import type { ReactElement } from "react";

export interface TrendPoint {
  readonly label: string;
  readonly value: number;
}

export function TrendChart({
  ariaLabel,
  points,
  unit,
}: {
  readonly ariaLabel: string;
  readonly points: readonly TrendPoint[];
  readonly unit?: string | null;
}): ReactElement {
  const finitePoints = points.filter((point) => Number.isFinite(point.value));
  if (finitePoints.length < 2) {
    return (
      <div className="flex min-h-56 items-center justify-center rounded-lg border border-dashed border-neutral-300 bg-neutral-50 p-6 text-center">
        <div>
          <p className="font-semibold text-neutral-800">Not enough data</p>
          <p className="mt-1 text-sm text-neutral-600">
            At least two valid readings are needed for a trend.
          </p>
        </div>
      </div>
    );
  }

  const values = finitePoints.map(({ value }) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const coordinates = finitePoints.map((point, index) => ({
    ...point,
    x: 24 + (index / (finitePoints.length - 1)) * 652,
    y: 24 + ((max - point.value) / range) * 172,
  }));
  const path = coordinates
    .map(
      ({ x, y }, index) => `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`,
    )
    .join(" ");

  return (
    <figure className="rounded-lg border border-neutral-200 bg-white p-4 shadow-panel">
      <svg
        aria-label={ariaLabel}
        className="h-64 w-full overflow-visible"
        preserveAspectRatio="none"
        role="img"
        viewBox="0 0 700 240"
      >
        {[24, 110, 196].map((y) => (
          <line className="stroke-neutral-200" key={y} x1="24" x2="676" y1={y} y2={y} />
        ))}
        <path
          className="fill-none stroke-purple-700"
          d={path}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
        {coordinates.map((point) => (
          <circle
            className="fill-purple-700 stroke-neutral-50"
            cx={point.x}
            cy={point.y}
            key={`${point.label}-${point.x}`}
            r="4"
          >
            <title>{`${point.label}: ${point.value}${unit ? ` ${unit}` : ""}`}</title>
          </circle>
        ))}
        <text className="fill-neutral-500 text-[11px]" x="24" y="220">
          {finitePoints[0].label}
        </text>
        <text className="fill-neutral-500 text-[11px]" textAnchor="end" x="676" y="220">
          {finitePoints.at(-1)?.label}
        </text>
        <text
          className="fill-neutral-500 text-[11px]"
          x="28"
          y="18"
        >{`${max.toLocaleString()}${unit ? ` ${unit}` : ""}`}</text>
      </svg>
      <figcaption className="sr-only">
        {ariaLabel}. Values range from {min} to {max}
        {unit ? ` ${unit}` : ""}.
      </figcaption>
    </figure>
  );
}
