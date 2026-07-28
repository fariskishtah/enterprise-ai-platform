import { useState, type FormEvent, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { acceptInvitation } from "../api/account";
import { ApiError } from "../api/client";
import { inputClassName } from "../components/intelligence/IntelligenceUi";

export function InvitationAcceptancePage(): ReactElement {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(
    token === null ? "This invitation link is invalid." : null,
  );

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (token === null) return;
    const form = new FormData(event.currentTarget);
    const fullName = String(form.get("fullName")).trim();
    const password = String(form.get("password"));
    setBusy(true);
    setError(null);
    void acceptInvitation({
      token,
      ...(fullName ? { full_name: fullName } : {}),
      ...(password ? { password } : {}),
    })
      .then(() => setAccepted(true))
      .catch((caught: unknown) =>
        setError(
          caught instanceof ApiError
            ? caught.message
            : "The invitation could not be accepted.",
        ),
      )
      .finally(() => setBusy(false));
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-stone-50 px-5 py-10">
      <section className="w-full max-w-lg rounded-xl border border-neutral-200 bg-white p-7 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800">
          FK SOLUTIONS
        </p>
        <h1 className="mt-4 text-2xl font-semibold text-neutral-950">
          {accepted ? "Invitation accepted" : "Join your team"}
        </h1>
        {accepted ? (
          <>
            <p className="mt-3 text-sm leading-6 text-neutral-600" role="status">
              Your account is ready with the role assigned by your company.
            </p>
            <Link
              className="mt-6 inline-block text-sm font-semibold text-purple-800 hover:underline"
              to="/login"
            >
              Continue to sign in
            </Link>
          </>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={submit}>
            <p className="text-sm leading-6 text-neutral-600">
              New users must choose a name and password. If you already have an account
              in this company, leave both fields empty.
            </p>
            <label className="block text-sm font-medium text-neutral-800">
              Full name
              <input className={inputClassName} minLength={2} name="fullName" />
            </label>
            <label className="block text-sm font-medium text-neutral-800">
              Password
              <input
                className={inputClassName}
                minLength={12}
                name="password"
                type="password"
              />
            </label>
            {error ? (
              <p className="text-sm text-red-700" role="alert">
                {error}
              </p>
            ) : null}
            <button
              className="rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
              disabled={busy || token === null}
              type="submit"
            >
              {busy ? "Accepting…" : "Accept invitation"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
