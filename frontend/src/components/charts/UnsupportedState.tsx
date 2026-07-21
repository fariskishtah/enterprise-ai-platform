import type { ReactElement } from "react";

interface UnsupportedStateProps {
  readonly reason: string;
  readonly title?: string;
}

/**
 * Standardised "not supported" panel used inside ChartPanel and standalone.
 * Color-blind safe: uses text and icon, not color alone.
 */
export function UnsupportedState({
  reason,
  title = "Not available",
}: UnsupportedStateProps): ReactElement {
  return (
    <div
      className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-muted/40 p-6 text-center"
      role="status"
      aria-label={title}
    >
      <svg
        aria-hidden="true"
        className="h-8 w-8 text-muted-foreground/60"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M18.364 18.364A9 9 0 0 0 5.636 5.636m12.728 12.728A9 9 0 0 1 5.636 5.636m12.728 12.728L5.636 5.636"
        />
      </svg>
      <p className="text-sm font-semibold text-muted-foreground">{title}</p>
      <p className="max-w-xs text-xs text-muted-foreground/80">{reason}</p>
    </div>
  );
}
