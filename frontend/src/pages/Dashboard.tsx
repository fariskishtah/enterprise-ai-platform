import type { ReactElement } from "react";

export function Dashboard(): ReactElement {
  return (
    <main className="min-h-screen bg-stone-50 text-neutral-950">
      <section className="mx-auto flex min-h-screen w-full max-w-6xl flex-col justify-center gap-10 px-6 py-10 sm:px-8">
        <div className="w-full border-l-4 border-teal-600 pl-6">
          <p className="text-sm font-semibold uppercase tracking-normal text-teal-700">
            Dashboard
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-normal text-neutral-950 sm:text-5xl">
            AI Manufacturing Platform
          </h1>
        </div>
        {import.meta.env.DEV ? (
          <aside className="rounded-2xl border border-teal-200 bg-white p-6 shadow-sm">
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
          </aside>
        ) : null}
      </section>
    </main>
  );
}
