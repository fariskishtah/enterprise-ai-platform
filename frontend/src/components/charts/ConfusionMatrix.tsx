import type { ReactElement } from "react";

export interface ConfusionMatrixData {
  readonly labels: readonly string[];
  readonly values: readonly (readonly number[])[];
}

interface ConfusionMatrixProps {
  readonly data: ConfusionMatrixData;
  readonly "aria-label"?: string;
}

/**
 * Confusion matrix rendered as an accessible colored table.
 * Color intensity scales per-cell using the maximum cell value.
 * Table semantics provide keyboard accessibility without relying on color alone.
 * Long class labels are truncated with title tooltip.
 */
export function ConfusionMatrix({
  data,
  "aria-label": ariaLabel = "Confusion matrix",
}: ConfusionMatrixProps): ReactElement {
  const { labels, values } = data;
  const maxValue = Math.max(...values.flatMap((row) => [...row]), 1);

  const totalCorrect = values.reduce((sum, row, i) => sum + (row[i] ?? 0), 0);
  const total = values.reduce((sum, row) => sum + row.reduce((s, v) => s + v, 0), 0);

  return (
    <div>
      <div className="overflow-x-auto rounded-md border border-border">
        <table
          aria-label={ariaLabel}
          className="min-w-full border-collapse text-center text-xs"
        >
          <caption className="sr-only">
            Confusion matrix. Rows represent actual classes, columns represent predicted
            classes. Overall accuracy:{" "}
            {total > 0 ? ((totalCorrect / total) * 100).toFixed(1) : "—"}%
          </caption>
          <thead>
            <tr>
              <th
                className="border border-border bg-muted px-3 py-2 text-left text-xs font-semibold text-muted-foreground"
                scope="col"
              >
                Actual ╲ Predicted
              </th>
              {labels.map((label) => (
                <th
                  className="border border-border bg-muted px-3 py-2 text-xs font-semibold text-muted-foreground"
                  key={label}
                  scope="col"
                  title={label}
                >
                  <span className="block max-w-[7rem] overflow-hidden text-ellipsis whitespace-nowrap">
                    {label}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {values.map((row, rowIndex) => (
              <tr key={labels[rowIndex]}>
                <th
                  className="border border-border bg-muted px-3 py-2 text-left text-xs font-semibold text-muted-foreground"
                  scope="row"
                  title={labels[rowIndex]}
                >
                  <span className="block max-w-[7rem] overflow-hidden text-ellipsis whitespace-nowrap">
                    {labels[rowIndex]}
                  </span>
                </th>
                {row.map((value, colIndex) => {
                  const intensity = maxValue > 0 ? value / maxValue : 0;
                  const isDiagonal = rowIndex === colIndex;
                  // Diagonal cells use purple hue, off-diagonal use neutral.
                  // Opacity encodes magnitude; text switches at 50% for contrast.
                  const bgStyle: React.CSSProperties = isDiagonal
                    ? {
                        backgroundColor: `rgba(109, 74, 255, ${Math.max(0.06, intensity * 0.75)})`,
                      }
                    : {
                        backgroundColor: `rgba(200, 190, 220, ${Math.max(0, intensity * 0.5)})`,
                      };
                  const textClass =
                    intensity > 0.5
                      ? isDiagonal
                        ? "font-bold text-purple-900 dark:text-purple-100"
                        : "font-semibold text-neutral-800 dark:text-neutral-200"
                      : "text-foreground";

                  return (
                    <td
                      className={`border border-border px-4 py-3 tabular-nums ${textClass}`}
                      key={colIndex}
                      style={bgStyle}
                      aria-label={`Actual ${labels[rowIndex]}, Predicted ${labels[colIndex]}: ${value}`}
                    >
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Overall accuracy:{" "}
        <strong>{total > 0 ? ((totalCorrect / total) * 100).toFixed(1) : "—"}%</strong>{" "}
        ({totalCorrect} / {total} correct). Diagonal cells show correct predictions.
      </p>
    </div>
  );
}
