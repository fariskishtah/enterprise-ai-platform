import type { ReactElement } from "react";

export function Dashboard(): ReactElement {
  return (
    <main className="min-h-screen bg-stone-50 text-neutral-950">
      <section className="mx-auto flex min-h-screen w-full max-w-6xl items-center px-6 py-10 sm:px-8">
        <div className="w-full border-l-4 border-teal-600 pl-6">
          <p className="text-sm font-semibold uppercase tracking-normal text-teal-700">
            Dashboard
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-normal text-neutral-950 sm:text-5xl">
            AI Manufacturing Platform
          </h1>
        </div>
      </section>
    </main>
  );
}
