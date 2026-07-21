import type { ReactElement, ReactNode } from "react";

interface PageHeaderProps {
  readonly actions?: ReactNode;
  readonly description: ReactNode;
  readonly eyebrow?: ReactNode;
  readonly headingId: string;
  readonly title: ReactNode;
}

/** Visual shell only: page data fetching and actions intentionally stay with pages. */
export function PageHeader({
  actions,
  description,
  eyebrow,
  headingId,
  title,
}: PageHeaderProps): ReactElement {
  return (
    <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow === undefined ? null : (
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-eyebrow">
            {eyebrow}
          </p>
        )}
        <h2
          className={`${eyebrow === undefined ? "" : "mt-2 "}text-3xl font-semibold tracking-tight text-foreground`}
          id={headingId}
        >
          {title}
        </h2>
        <div className="mt-2 max-w-2xl text-sm leading-6 text-secondary-foreground">
          {description}
        </div>
      </div>
      {actions === undefined ? null : (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}
