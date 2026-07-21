import type { ReactElement } from "react";

export interface ScatterPoint {
  readonly x: number;
  readonly y: number;
}

interface ScatterChartProps {
  readonly points: readonly ScatterPoint[];
  readonly xLabel: string;
  readonly yLabel: string;
  /** Show y=x identity reference line */
  readonly showIdentityLine?: boolean;
  /** Show y=0 horizontal reference line */
  readonly showZeroLine?: boolean;
  readonly "aria-label": string;
  readonly summary?: string;
  readonly pointColor?: string;
  readonly pointRadius?: number;
}

const W = 580;
const H = 300;
const PAD = { top: 16, right: 20, bottom: 46, left: 54 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function scale(value: number, min: number, max: number, size: number): number {
  if (max === min) return size / 2;
  return ((value - min) / (max - min)) * size;
}

function ticks(min: number, max: number, count = 5): number[] {
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + i * step);
}

function fmtNum(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toExponential(1);
  if (abs >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

/**
 * Scatter chart for actual-vs-predicted and residual plots.
 * Points are bounded by the backend (≤200). Identity and zero lines are optional.
 * Accessible: role=img with aria-label, figcaption summary.
 */
export function ScatterChart({
  points,
  xLabel,
  yLabel,
  showIdentityLine = false,
  showZeroLine = false,
  "aria-label": ariaLabel,
  summary,
  pointColor = "#6d4aff",
  pointRadius = 3,
}: ScatterChartProps): ReactElement {
  if (points.length === 0) {
    return <p className="text-sm text-muted-foreground">No points to display.</p>;
  }

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys, showZeroLine ? 0 : Math.min(...ys));
  const yMax = Math.max(...ys);

  const px = (x: number) => PAD.left + scale(x, xMin, xMax, PLOT_W);
  const py = (y: number) => PAD.top + PLOT_H - scale(y, yMin, yMax, PLOT_H);

  const xTickValues = ticks(xMin, xMax);
  const yTickValues = ticks(yMin, yMax);

  return (
    <figure>
      <svg
        aria-label={ariaLabel}
        className="h-auto w-full overflow-visible"
        role="img"
        viewBox={`0 0 ${W} ${H}`}
      >
        {/* Grid */}
        {yTickValues.map((v) => (
          <line
            key={`gy-${v}`}
            stroke="currentColor"
            strokeOpacity={0.08}
            x1={PAD.left}
            x2={PAD.left + PLOT_W}
            y1={py(v)}
            y2={py(v)}
          />
        ))}

        {/* Identity reference line y=x */}
        {showIdentityLine ? (
          <line
            stroke="currentColor"
            strokeDasharray="4 4"
            strokeOpacity={0.4}
            strokeWidth={1.5}
            x1={px(xMin)}
            x2={px(xMax)}
            y1={py(xMin)}
            y2={py(xMax)}
          />
        ) : null}

        {/* Zero reference line y=0 */}
        {showZeroLine && yMin <= 0 && yMax >= 0 ? (
          <line
            stroke="currentColor"
            strokeDasharray="4 4"
            strokeOpacity={0.4}
            strokeWidth={1.5}
            x1={PAD.left}
            x2={PAD.left + PLOT_W}
            y1={py(0)}
            y2={py(0)}
          />
        ) : null}

        {/* Points */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={px(p.x)}
            cy={py(p.y)}
            fill={pointColor}
            fillOpacity={0.55}
            r={pointRadius}
          >
            <title>
              {xLabel}: {fmtNum(p.x)}, {yLabel}: {fmtNum(p.y)}
            </title>
          </circle>
        ))}

        {/* Axes */}
        <line
          stroke="currentColor"
          strokeOpacity={0.3}
          x1={PAD.left}
          x2={PAD.left + PLOT_W}
          y1={PAD.top + PLOT_H}
          y2={PAD.top + PLOT_H}
        />
        <line
          stroke="currentColor"
          strokeOpacity={0.3}
          x1={PAD.left}
          x2={PAD.left}
          y1={PAD.top}
          y2={PAD.top + PLOT_H}
        />

        {/* X ticks */}
        {xTickValues.map((v) => (
          <text
            key={`xt-${v}`}
            className="fill-muted-foreground text-[10px]"
            textAnchor="middle"
            x={px(v)}
            y={PAD.top + PLOT_H + 14}
          >
            {fmtNum(v)}
          </text>
        ))}

        {/* Y ticks */}
        {yTickValues.map((v) => (
          <text
            key={`yt-${v}`}
            className="fill-muted-foreground text-[10px]"
            dominantBaseline="middle"
            textAnchor="end"
            x={PAD.left - 6}
            y={py(v)}
          >
            {fmtNum(v)}
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

      <figcaption className="sr-only">
        {ariaLabel}.{" "}
        {summary ??
          `${points.length} bounded held-out points. X range: ${fmtNum(xMin)} to ${fmtNum(xMax)}. Y range: ${fmtNum(yMin)} to ${fmtNum(yMax)}.`}
      </figcaption>
    </figure>
  );
}
