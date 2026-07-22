import type { ReactElement } from "react";

export interface HorizontalBarItem {
  readonly feature: string;
  readonly value: number;
}

interface HorizontalBarChartProps {
  readonly items: readonly HorizontalBarItem[];
  readonly "aria-label": string;
  readonly maxItems?: number;
  readonly positiveColor?: string;
  readonly negativeColor?: string;
  readonly sourceNote?: string;
  readonly showZeroLine?: boolean;
}

/**
 * Horizontal bar chart for feature importance, coefficients, permutation importance.
 * Supports positive and negative values with zero reference line.
 * Items are already ranked by the backend (by absolute value).
 * Accessible: role=list with feature name + value text, not color alone.
 */
export function HorizontalBarChart({
  items,
  "aria-label": ariaLabel,
  maxItems = 30,
  positiveColor = "#6d4aff",
  negativeColor = "#e04f56",
  sourceNote,
  showZeroLine = true,
}: HorizontalBarChartProps): ReactElement {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No data to display.</p>;
  }

  const displayed = items.slice(0, maxItems);
  const maxAbsValue = Math.max(...displayed.map((item) => Math.abs(item.value)), 1e-10);
  const hasNegative = displayed.some((item) => item.value < 0);

  // Bar width as % of half-width (50% for positive, 50% for negative).
  // All bars extend from center when hasNegative, from left when all positive.
  const barPct = (value: number) =>
    (Math.abs(value) / maxAbsValue) * (hasNegative ? 50 : 100);

  const fmtVal = (v: number) => {
    const abs = Math.abs(v);
    if (abs < 0.0001 && abs > 0) return v.toExponential(2);
    if (abs >= 1000) return v.toFixed(0);
    return v.toFixed(4);
  };

  return (
    <div aria-label={ariaLabel} role="list">
      {sourceNote ? (
        <p className="mb-3 text-xs text-muted-foreground">{sourceNote}</p>
      ) : null}

      {hasNegative ? (
        <div className="mb-1 flex justify-between text-[10px] text-muted-foreground/70">
          <span>← Negative</span>
          <span>0</span>
          <span>Positive →</span>
        </div>
      ) : null}

      <div className="space-y-1.5">
        {displayed.map((item) => {
          const isPositive = item.value >= 0;
          const pct = barPct(item.value);
          const color = isPositive ? positiveColor : negativeColor;

          return (
            <div
              className="flex items-center gap-2 text-xs"
              key={item.feature}
              role="listitem"
            >
              {/* Feature name */}
              <span
                className="w-32 shrink-0 overflow-hidden text-ellipsis whitespace-nowrap text-right text-muted-foreground"
                title={item.feature}
              >
                {item.feature}
              </span>

              {/* Bar track */}
              <div className="relative flex-1">
                {hasNegative ? (
                  <div className="flex h-5 w-full overflow-hidden rounded-sm">
                    {/* Left half (negative) */}
                    <div className="relative flex h-full w-1/2 justify-end overflow-hidden rounded-l-sm bg-muted/30">
                      {!isPositive ? (
                        <div
                          aria-hidden="true"
                          className="h-full rounded-l-sm"
                          style={{
                            width: `${pct * 2}%`,
                            backgroundColor: color,
                            opacity: 0.8,
                          }}
                        />
                      ) : null}
                    </div>
                    {/* Center zero line */}
                    {showZeroLine ? <div className="w-px shrink-0 bg-border" /> : null}
                    {/* Right half (positive) */}
                    <div className="relative flex h-full w-1/2 overflow-hidden rounded-r-sm bg-muted/30">
                      {isPositive ? (
                        <div
                          aria-hidden="true"
                          className="h-full rounded-r-sm"
                          style={{
                            width: `${pct * 2}%`,
                            backgroundColor: color,
                            opacity: 0.8,
                          }}
                        />
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <div className="h-5 overflow-hidden rounded-sm bg-muted/30">
                    <div
                      aria-hidden="true"
                      className="h-full rounded-sm"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: color,
                        opacity: 0.8,
                      }}
                    />
                  </div>
                )}
              </div>

              {/* Value — always visible, not just in tooltip */}
              <span
                className="w-20 shrink-0 tabular-nums text-muted-foreground"
                aria-label={`${item.feature}: ${fmtVal(item.value)}`}
              >
                {fmtVal(item.value)}
              </span>
            </div>
          );
        })}
      </div>

      {items.length > maxItems ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing top {maxItems} of {items.length} features by absolute value.
        </p>
      ) : null}
    </div>
  );
}
