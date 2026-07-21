import type { ReactElement, ReactNode } from "react";

import { UnsupportedState } from "./UnsupportedState";

interface ChartPanelProps {
  readonly title: string;
  readonly headingLevel?: "h2" | "h3";
  readonly description?: string;
  readonly children: ReactNode;
  readonly isLoading?: boolean;
  readonly isEmpty?: boolean;
  readonly emptyMessage?: string;
  readonly isUnsupported?: boolean;
  readonly unsupportedReason?: string;
  readonly error?: string | null;
  readonly className?: string;
  readonly "aria-label"?: string;
}

/**
 * Wrapper that handles loading, empty, unsupported, and error states for any chart.
 * Partial chart failure stays local — an error here does not crash the page.
 */
export function ChartPanel({
  title,
  headingLevel: Heading = "h3",
  description,
  children,
  isLoading = false,
  isEmpty = false,
  emptyMessage = "No data available.",
  isUnsupported = false,
  unsupportedReason = "Not supported for this model.",
  error = null,
  className = "",
  "aria-label": ariaLabel,
}: ChartPanelProps): ReactElement {
  const label = ariaLabel ?? title;

  return (
    <section
      aria-label={label}
      className={`rounded-lg border border-border bg-card p-5 ${className}`}
    >
      <Heading className="text-base font-semibold text-foreground">{title}</Heading>
      {description ? (
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      ) : null}
      <div className="mt-4">
        {isLoading ? (
          <div
            aria-busy="true"
            aria-label="Loading chart"
            className="flex min-h-32 items-center justify-center"
            role="status"
          >
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
          </div>
        ) : error ? (
          <div
            className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-lg border border-danger-200 bg-danger-50 p-4 text-center"
            role="alert"
          >
            <p className="text-sm font-semibold text-danger-900">Chart error</p>
            <p className="text-xs text-danger-800">{error}</p>
          </div>
        ) : isUnsupported ? (
          <UnsupportedState reason={unsupportedReason} />
        ) : isEmpty ? (
          <UnsupportedState title="No data" reason={emptyMessage} />
        ) : (
          children
        )}
      </div>
    </section>
  );
}
