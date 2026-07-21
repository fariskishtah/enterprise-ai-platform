import type { ReactElement } from "react";
import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";

const returnLinkClassName =
  "mt-6 inline-flex rounded-lg bg-purple-700 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700";

export function NotFoundPage(): ReactElement {
  return (
    <section aria-labelledby="not-found-heading" className="max-w-2xl">
      <p className="text-sm font-semibold uppercase tracking-wider text-purple-700">
        404
      </p>
      <h2
        className="mt-2 text-3xl font-semibold tracking-tight text-neutral-950"
        id="not-found-heading"
      >
        Page not found
      </h2>
      <p className="mt-3 text-base leading-7 text-neutral-600">
        The requested workspace does not exist or has moved.
      </p>
      <Link className={returnLinkClassName} to="/">
        Return to Dashboard
      </Link>
    </section>
  );
}

export function RouteErrorPage(): ReactElement {
  const error = useRouteError();
  const status = isRouteErrorResponse(error) ? error.status : 500;

  return (
    <main className="flex min-h-screen items-center justify-center bg-stone-50 px-6 text-neutral-950">
      <section aria-labelledby="route-error-heading" className="max-w-lg text-center">
        <p className="text-sm font-semibold uppercase tracking-wider text-purple-700">
          Error {status}
        </p>
        <h1
          className="mt-2 text-3xl font-semibold tracking-tight"
          id="route-error-heading"
        >
          This page could not be displayed
        </h1>
        <p className="mt-3 text-base leading-7 text-neutral-600">
          Return to the Dashboard and try again.
        </p>
        <Link className={returnLinkClassName} to="/">
          Return to Dashboard
        </Link>
      </section>
    </main>
  );
}
