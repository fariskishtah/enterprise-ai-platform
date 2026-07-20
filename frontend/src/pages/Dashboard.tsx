import type { ReactElement } from "react";

import { StatusBadge } from "../components/StatusBadge";

export function Dashboard(): ReactElement {
  return (
    <section aria-labelledby="dashboard-heading">
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-teal-700">
            Operations overview
          </p>
          <h2
            className="mt-2 text-3xl font-semibold tracking-tight text-neutral-950"
            id="dashboard-heading"
          >
            AI Manufacturing Platform
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-600">
            A focused workspace for manufacturing operations and governed model
            lifecycle activity.
          </p>
        </div>
        <StatusBadge label="Platform healthy" status="healthy" />
      </div>

      {import.meta.env.DEV ? (
        <aside className="mt-8 rounded-lg border border-teal-200 bg-white p-6">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-widest text-teal-700">
              Local demo
            </p>
            <h2 className="mt-2 text-2xl font-semibold">
              Predictive maintenance in one bounded workflow
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-neutral-600">
              Seed a sample factory, machine, spindle sensor, realistic readings, one
              tiny trained model, a prediction, and its monitoring audit with
              <code className="mx-1 rounded bg-stone-100 px-1.5 py-0.5 text-neutral-800">
                ./scripts/seed-demo.sh
              </code>
            </p>
            <a
              className="mt-5 inline-flex rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800"
              href="http://localhost:8000/docs"
            >
              Explore the local API
            </a>
          </div>
        </aside>
      ) : null}
    </section>
  );
}
