import type { ReactElement } from "react";
import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";

const returnLinkClassName =
  "mt-6 inline-flex rounded-lg bg-[var(--button-primary)] px-4 py-2 text-sm font-semibold text-white hover:bg-[var(--button-primary-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]";

export function NotFoundPage(): ReactElement {
  return (
    <section aria-labelledby="not-found-heading" className="max-w-2xl">
      <p className="text-sm font-semibold uppercase tracking-wider text-eyebrow">404</p>
      <h2
        className="mt-2 text-3xl font-semibold tracking-tight text-foreground"
        id="not-found-heading"
      >
        Page not found
      </h2>
      <p className="mt-3 text-base leading-7 text-secondary-foreground">
        The requested workspace does not exist or has moved.
      </p>
      <Link className={returnLinkClassName} to="/">
        Return to Dashboard
      </Link>
    </section>
  );
}

export function ForbiddenPage(): ReactElement {
  return (
    <section aria-labelledby="forbidden-heading" className="max-w-2xl">
      <p className="text-sm font-semibold uppercase tracking-wider text-eyebrow">403</p>
      <h2
        className="mt-2 text-3xl font-semibold tracking-tight text-foreground"
        id="forbidden-heading"
      >
        Access restricted
      </h2>
      <p className="mt-3 text-base leading-7 text-secondary-foreground">
        Your current company role does not permit this action. Ask a company
        administrator if your responsibilities have changed.
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

  if (status === 404) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-canvas px-6 text-foreground">
        <NotFoundPage />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-6 text-foreground">
      <section aria-labelledby="route-error-heading" className="max-w-lg text-center">
        <p className="text-sm font-semibold uppercase tracking-wider text-eyebrow">
          Error {status}
        </p>
        <h1
          className="mt-2 text-3xl font-semibold tracking-tight"
          id="route-error-heading"
        >
          This page could not be displayed
        </h1>
        <p className="mt-3 text-base leading-7 text-secondary-foreground">
          Return to the Dashboard and try again.
        </p>
        <Link className={returnLinkClassName} to="/">
          Return to Dashboard
        </Link>
      </section>
    </main>
  );
}
