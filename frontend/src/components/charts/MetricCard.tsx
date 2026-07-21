import type { ReactElement } from "react";

interface MetricCardProps {
  readonly label: string;
  readonly value: number | null | undefined;
  readonly digits?: number;
  readonly unit?: string;
  readonly direction?: "higher-better" | "lower-better" | "neutral";
  readonly omittedReason?: string;
}

/**
 * Single metric display card. Shows "—" when value is undefined/null.
 * Accessible: label and value are both in readable text, not just styled color.
 */
export function MetricCard({
  label,
  value,
  digits = 4,
  unit,
  direction,
  omittedReason,
}: MetricCardProps): ReactElement {
  const formatted =
    value === null || value === undefined
      ? "—"
      : `${Number.isFinite(value) ? value.toFixed(digits) : "—"}${unit ? ` ${unit}` : ""}`;

  const directionIcon =
    direction === "higher-better" ? " ↑" : direction === "lower-better" ? " ↓" : "";

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label.replaceAll("_", " ")}
        {directionIcon ? (
          <span
            aria-label={
              direction === "higher-better" ? "higher is better" : "lower is better"
            }
          >
            {directionIcon}
          </span>
        ) : null}
      </p>
      {omittedReason ? (
        <p
          className="mt-1 text-sm italic text-muted-foreground/70"
          title={omittedReason}
        >
          Omitted
        </p>
      ) : (
        <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
          {formatted}
        </p>
      )}
    </div>
  );
}
