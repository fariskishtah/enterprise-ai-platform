import type { ReactElement } from "react";

export interface HistogramBin {
  readonly start: number;
  readonly end: number;
  readonly count: number;
}

interface HistogramChartProps {
  readonly bins: readonly HistogramBin[];
  readonly xLabel: string;
  readonly yLabel?: string;
  readonly "aria-label": string;
  readonly showZeroReference?: boolean;
  readonly barColor?: string;
}

const W = 580;
const H = 220;
const PAD = { top: 16, right: 16, bottom: 46, left: 50 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function fmtNum(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toExponential(1);
  if (abs >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

/**
 * Histogram chart from pre-binned backend data.
 * Exact bin ranges and counts shown in tooltips. No interpolation.
 * Accessible: role=img, figcaption with summary. Accessible table below for screen readers.
 */
export function HistogramChart({
  bins,
  xLabel,
  yLabel = "Count",
  "aria-label": ariaLabel,
  showZeroReference = false,
  barColor = "#6d4aff",
}: HistogramChartProps): ReactElement {
  if (bins.length === 0) {
    return <p className="text-sm text-muted-foreground">No histogram data.</p>;
  }

  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const xMin = bins[0].start;
  const xMax = bins[bins.length - 1].end;
  const xRange = xMax - xMin || 1;
  const totalCount = bins.reduce((s, b) => s + b.count, 0);

  const px = (v: number) => PAD.left + ((v - xMin) / xRange) * PLOT_W;
  const barH = (count: number) => (count / maxCount) * PLOT_H;

  const yTicks = [0, 0.25, 0.5, 0.75, 1.0].map((f) => Math.round(f * maxCount));

  return (
    <div>
      <figure>
        <svg
          aria-label={ariaLabel}
          className="h-auto w-full overflow-visible"
          role="img"
          viewBox={`0 0 ${W} ${H}`}
        >
          {/* Grid */}
          {yTicks.map((v) => (
            <line
              key={`g-${v}`}
              stroke="currentColor"
              strokeOpacity={0.08}
              x1={PAD.left}
              x2={PAD.left + PLOT_W}
              y1={PAD.top + PLOT_H - barH(v)}
              y2={PAD.top + PLOT_H - barH(v)}
            />
          ))}

          {/* Zero reference (for residual histograms) */}
          {showZeroReference && xMin <= 0 && xMax >= 0 ? (
            <line
              stroke="currentColor"
              strokeDasharray="4 4"
              strokeOpacity={0.45}
              strokeWidth={1.5}
              x1={px(0)}
              x2={px(0)}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
            />
          ) : null}

          {/* Bars */}
          {bins.map((bin, i) => {
            const x = px(bin.start);
            const w = Math.max(1, px(bin.end) - px(bin.start) - 1);
            const h = barH(bin.count);
            return (
              <rect
                key={i}
                fill={barColor}
                fillOpacity={0.75}
                height={h}
                width={w}
                x={x}
                y={PAD.top + PLOT_H - h}
              >
                <title>
                  Range: {fmtNum(bin.start)} – {fmtNum(bin.end)}, Count: {bin.count}
                </title>
              </rect>
            );
          })}

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

          {/* X ticks — start and end of each bin */}
          {[xMin, xMax].map((v) => (
            <text
              key={`xt-${v}`}
              className="fill-muted-foreground text-[10px]"
              textAnchor={v === xMin ? "start" : "end"}
              x={px(v)}
              y={PAD.top + PLOT_H + 14}
            >
              {fmtNum(v)}
            </text>
          ))}
          {bins.length <= 10
            ? bins.map((bin) => (
                <text
                  key={`xtm-${bin.start}`}
                  className="fill-muted-foreground text-[9px]"
                  textAnchor="middle"
                  x={px((bin.start + bin.end) / 2)}
                  y={PAD.top + PLOT_H + 14}
                >
                  {fmtNum((bin.start + bin.end) / 2)}
                </text>
              ))
            : null}

          {/* Y ticks */}
          {yTicks.map((v) => (
            <text
              key={`yt-${v}`}
              className="fill-muted-foreground text-[10px]"
              dominantBaseline="middle"
              textAnchor="end"
              x={PAD.left - 4}
              y={PAD.top + PLOT_H - barH(v)}
            >
              {v}
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
          {ariaLabel}. {bins.length} bins, {totalCount} total observations. Range:{" "}
          {fmtNum(xMin)} to {fmtNum(xMax)}.
        </figcaption>
      </figure>

      {/* Accessible data table for screen readers */}
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          View data table
        </summary>
        <div className="mt-2 max-h-48 overflow-auto rounded-md border border-border">
          <table className="min-w-full text-xs">
            <thead className="bg-muted">
              <tr>
                <th className="px-3 py-1 text-left">Start</th>
                <th className="px-3 py-1 text-left">End</th>
                <th className="px-3 py-1 text-right">Count</th>
              </tr>
            </thead>
            <tbody>
              {bins.map((bin, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="px-3 py-1 tabular-nums">{fmtNum(bin.start)}</td>
                  <td className="px-3 py-1 tabular-nums">{fmtNum(bin.end)}</td>
                  <td className="px-3 py-1 text-right tabular-nums">{bin.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
