import type { ReactElement } from "react";

interface PlaceholderPageProps {
  readonly description: string;
  readonly title: string;
}

export function PlaceholderPage({
  description,
  title,
}: PlaceholderPageProps): ReactElement {
  return (
    <section aria-labelledby="page-heading">
      <div className="max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-wider text-purple-700">
          Controlled pilot
        </p>
        <h2
          className="mt-2 text-3xl font-semibold tracking-tight text-neutral-950"
          id="page-heading"
        >
          {title}
        </h2>
        <p className="mt-3 text-base leading-7 text-neutral-600">{description}</p>
      </div>
      <div className="mt-8 rounded-lg border border-dashed border-neutral-300 bg-white p-6">
        <p className="text-sm font-medium text-neutral-600">
          This capability is intentionally unavailable in this release. Contact the
          deployment owner for approved account provisioning.
        </p>
      </div>
    </section>
  );
}
