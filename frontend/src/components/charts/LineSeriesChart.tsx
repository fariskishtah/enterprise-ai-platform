import type { ReactElement } from "react";

export interface LineSeriesPoint {
  readonly x: number;
  readonly y: number;
  readonly threshold?: number | null;
}

export interface LineSeries {
  readonly label: string;
  readonly points: readonly LineSeriesPoint[];
  readonly color?: string;
  readonly dashed?: boolean;
}

interface LineSeriesChartProps {
  readonly series: readonly LineSeries[];
  /** Optional diagonal reference line (e.g., random-chance line for ROC) */
  readonly showDiagonal?: boolean;
  /** Optional horizontal reference line */
  readonly referenceY?: number;
  /** Optional vertical reference line */
  readonly referenceX?: number;
  readonly xLabel: string;
  readonly yLabel: string;
  readonly "aria-label": string;
  readonly summary?: string;
  /** Force y-axis to [0,1] */
  readonly yUnit?: boolean;
  /** Force x-axis to [0,1] */
  readonly xUnit?: boolean;
}

const W = 580;
const H = 260;
const PAD = { top: 16, right: 20, bottom: 46, left: 54 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const COLORS = [
  "#6d4aff",
  "#e04f56",
  "#198754",
  "#f59e0b",
  "#0ea5e9",
  "#a855f7",
  "#ec4899",
];

function scale(value: number, min: number, max: number, size: number): number {
  if (max === min) return size / 2;
  return ((value - min) / (max - min)) * size;
}

function ticks(min: number, max: number, count = 5): number[] {
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + i * step);
}

/**
 * Generic SVG line series chart. Used for ROC, precision-recall, calibration.
 * Accessible: role=img with aria-label, figcaption summary, no tooltip-only values.
 * Prefers-reduced-motion: no animated transitions.
 */
export function LineSeriesChart({
  series,
  showDiagonal = false,
  referenceY,
  referenceX,
  xLabel,
  yLabel,
  "aria-label": ariaLabel,
  summary,
  yUnit = false,
  xUnit = false,
}: LineSeriesChartProps): ReactElement {
  if (series.length === 0 || series.every((s) => s.points.length === 0)) {
    return <p className="text-sm text-muted-foreground">No series data to display.</p>;
  }

  const allX = series.flatMap((s) => s.points.map((p) => p.x));
  const allY = series.flatMap((s) => s.points.map((p) => p.y));
  const xMin = xUnit ? 0 : Math.min(...allX);
  const xMax = xUnit ? 1 : Math.max(...allX);
  const yMin = yUnit ? 0 : Math.min(0, Math.min(...allY));
  const yMax = yUnit ? 1 : Math.max(...allY);

  const px = (x: number) => PAD.left + scale(x, xMin, xMax, PLOT_W);
  const py = (y: number) => PAD.top + PLOT_H - scale(y, yMin, yMax, PLOT_H);

  const xTickValues = ticks(xMin, xMax);
  const yTickValues = ticks(yMin, yMax);

  return (
    <div>
      <figure>
        <svg
          aria-label={ariaLabel}
          className="h-auto w-full overflow-visible"
          role="img"
          viewBox={`0 0 ${W} ${H}`}
        >
          {/* Grid lines */}
          {yTickValues.map((v) => (
            <line
              key={`gy-${v}`}
              x1={PAD.left}
              x2={PAD.left + PLOT_W}
              y1={py(v)}
              y2={py(v)}
              stroke="currentColor"
              strokeOpacity={0.1}
              strokeWidth={1}
            />
          ))}
          {xTickValues.map((v) => (
            <line
              key={`gx-${v}`}
              x1={px(v)}
              x2={px(v)}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
              stroke="currentColor"
              strokeOpacity={0.1}
              strokeWidth={1}
            />
          ))}

          {/* Diagonal reference (ROC random chance) */}
          {showDiagonal ? (
            <line
              stroke="currentColor"
              strokeDasharray="4 4"
              strokeOpacity={0.4}
              strokeWidth={1.5}
              x1={px(xMin)}
              x2={px(xMax)}
              y1={py(yMin)}
              y2={py(yMax)}
            />
          ) : null}

          {/* Horizontal reference */}
          {referenceY !== undefined ? (
            <line
              stroke="currentColor"
              strokeDasharray="4 4"
              strokeOpacity={0.4}
              strokeWidth={1.5}
              x1={PAD.left}
              x2={PAD.left + PLOT_W}
              y1={py(referenceY)}
              y2={py(referenceY)}
            />
          ) : null}

          {/* Vertical reference */}
          {referenceX !== undefined ? (
            <line
              stroke="currentColor"
              strokeDasharray="4 4"
              strokeOpacity={0.4}
              strokeWidth={1.5}
              x1={px(referenceX)}
              x2={px(referenceX)}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
            />
          ) : null}

          {/* Series lines */}
          {series.map((s, seriesIndex) => {
            const color = s.color ?? COLORS[seriesIndex % COLORS.length];
            const d = s.points
              .map(
                (p, i) =>
                  `${i === 0 ? "M" : "L"} ${px(p.x).toFixed(1)} ${py(p.y).toFixed(1)}`,
              )
              .join(" ");
            return (
              <path
                key={s.label}
                d={d}
                fill="none"
                stroke={color}
                strokeDasharray={s.dashed ? "5 3" : undefined}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
              />
            );
          })}

          {/* X axis */}
          <line
            stroke="currentColor"
            strokeOpacity={0.3}
            x1={PAD.left}
            x2={PAD.left + PLOT_W}
            y1={PAD.top + PLOT_H}
            y2={PAD.top + PLOT_H}
          />
          {/* Y axis */}
          <line
            stroke="currentColor"
            strokeOpacity={0.3}
            x1={PAD.left}
            x2={PAD.left}
            y1={PAD.top}
            y2={PAD.top + PLOT_H}
          />

          {/* X tick labels */}
          {xTickValues.map((v) => (
            <text
              key={`xt-${v}`}
              className="fill-muted-foreground text-[10px]"
              textAnchor="middle"
              x={px(v)}
              y={PAD.top + PLOT_H + 14}
            >
              {v.toFixed(xMax <= 1 ? 1 : 0)}
            </text>
          ))}

          {/* Y tick labels */}
          {yTickValues.map((v) => (
            <text
              key={`yt-${v}`}
              className="fill-muted-foreground text-[10px]"
              dominantBaseline="middle"
              textAnchor="end"
              x={PAD.left - 6}
              y={py(v)}
            >
              {v.toFixed(yMax <= 1 ? 1 : 0)}
            </text>
          ))}

          {/* Axis labels */}
          <text
            className="fill-muted-foreground text-[11px]"
            textAnchor="middle"
            x={PAD.left + PLOT_W / 2}
            y={H - 4}
          >
            {xLabel}
          </text>
          <text
            className="fill-muted-foreground text-[11px]"
            textAnchor="middle"
            transform={`rotate(-90,${12},${PAD.top + PLOT_H / 2})`}
            x={12}
            y={PAD.top + PLOT_H / 2}
          >
            {yLabel}
          </text>
        </svg>

        {/* Legend — accessible, not color-only */}
        {series.length > 1 ? (
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" role="list">
            {series.map((s, i) => {
              const color = s.color ?? COLORS[i % COLORS.length];
              return (
                <li className="flex items-center gap-1.5" key={s.label}>
                  <span
                    aria-hidden="true"
                    className="inline-block h-2 w-4 rounded-sm"
                    style={{ backgroundColor: color }}
                  />
                  {s.dashed ? (
                    <span className="text-muted-foreground">{s.label} (dashed)</span>
                  ) : (
                    <span className="text-muted-foreground">{s.label}</span>
                  )}
                </li>
              );
            })}
          </ul>
        ) : null}

        {summary ? (
          <figcaption className="sr-only">
            {ariaLabel}. {summary}
          </figcaption>
        ) : (
          <figcaption className="sr-only">{ariaLabel}</figcaption>
        )}
      </figure>
    </div>
  );
}
