import type { ReactElement, ReactNode } from "react";
import { Link } from "react-router-dom";

interface BreadcrumbItem {
  readonly label: string;
  readonly to?: string;
}

export function Breadcrumbs({
  items,
}: {
  readonly items: readonly BreadcrumbItem[];
}): ReactElement {
  return (
    <nav aria-label="Breadcrumb" className="mb-5 text-sm text-neutral-600">
      <ol className="flex flex-wrap items-center gap-2">
        {items.map((item, index) => (
          <li className="flex items-center gap-2" key={`${item.label}-${index}`}>
            {index > 0 ? <span aria-hidden="true">/</span> : null}
            {item.to === undefined ? (
              <span aria-current="page" className="font-medium text-neutral-900">
                {item.label}
              </span>
            ) : (
              <Link className="hover:text-teal-700 hover:underline" to={item.to}>
                {item.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function EmptyState({
  action,
  description,
  title,
}: {
  readonly action?: ReactNode;
  readonly description: string;
  readonly title: string;
}): ReactElement {
  return (
    <div className="rounded-lg border border-dashed border-neutral-300 bg-white px-6 py-10 text-center">
      <h3 className="text-base font-semibold text-neutral-900">{title}</h3>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-neutral-600">
        {description}
      </p>
      {action === undefined ? null : <div className="mt-5">{action}</div>}
    </div>
  );
}

export function InlineError({
  message,
  onRetry,
}: {
  readonly message: string;
  readonly onRetry: () => void;
}): ReactElement {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-5" role="alert">
      <h3 className="font-semibold text-red-900">Unable to load this workspace</h3>
      <p className="mt-1 text-sm text-red-800">{message}</p>
      <button
        className="mt-4 rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
        onClick={onRetry}
        type="button"
      >
        Try again
      </button>
    </div>
  );
}

export function LoadingSkeleton({
  label = "Loading resources",
}: {
  readonly label?: string;
}): ReactElement {
  return (
    <div aria-busy="true" aria-label={label} className="space-y-3" role="status">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((item) => (
        <div
          className="h-24 animate-pulse rounded-lg border border-neutral-200 bg-neutral-100"
          key={item}
        />
      ))}
    </div>
  );
}

export function PaginationControls({
  limit,
  offset,
  onPageChange,
  total,
}: {
  readonly limit: number;
  readonly offset: number;
  readonly onPageChange: (offset: number) => void;
  readonly total: number;
}): ReactElement | null {
  if (total <= limit) {
    return null;
  }
  const first = offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-4">
      <p className="text-sm text-neutral-600">
        Showing {first}–{last} of {total}
      </p>
      <div className="flex gap-2">
        <button
          className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={offset === 0}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          type="button"
        >
          Previous
        </button>
        <button
          className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={offset + limit >= total}
          onClick={() => onPageChange(offset + limit)}
          type="button"
        >
          Next
        </button>
      </div>
    </div>
  );
}

export const primaryButtonClassName =
  "rounded-md bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-60";

export const secondaryButtonClassName =
  "rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-semibold text-neutral-800 hover:bg-neutral-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-60";
