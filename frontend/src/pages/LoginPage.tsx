import { useState, type FormEvent, type ReactElement } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

interface LoginLocationState {
  readonly from?: string;
}

export function LoginPage(): ReactElement {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const requestedDestination = (location.state as LoginLocationState | null)?.from;
  const destination =
    requestedDestination?.startsWith("/") === true &&
    !requestedDestination.startsWith("//")
      ? requestedDestination
      : "/";

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    auth.clearNotice();
    setSubmitting(true);
    try {
      await auth.login({ email, password });
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Sign in failed. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen bg-stone-50 text-neutral-950">
      <section className="flex w-full items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-md rounded-xl border border-neutral-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="mb-8 flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-md bg-teal-700 text-sm font-bold text-white">
              FM
            </span>
            <div>
              <p className="font-semibold">FactoryMind</p>
              <p className="text-sm text-neutral-500">AI Manufacturing</p>
            </div>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-2 text-sm leading-6 text-neutral-600">
            Use your platform account to access the operations workspace.
          </p>

          {auth.notice !== null ? (
            <div
              className="mt-6 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
              role="status"
            >
              {auth.notice}
            </div>
          ) : null}
          {error !== null ? (
            <div
              className="mt-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {error}
            </div>
          ) : null}

          <form className="mt-6 space-y-5" onSubmit={submit}>
            <div>
              <label
                className="block text-sm font-medium text-neutral-800"
                htmlFor="email"
              >
                Email address
              </label>
              <input
                autoComplete="email"
                className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none transition focus:border-teal-700 focus:ring-2 focus:ring-teal-700/20"
                disabled={submitting}
                id="email"
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </div>
            <div>
              <label
                className="block text-sm font-medium text-neutral-800"
                htmlFor="password"
              >
                Password
              </label>
              <input
                autoComplete="current-password"
                className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none transition focus:border-teal-700 focus:ring-2 focus:ring-teal-700/20"
                disabled={submitting}
                id="password"
                maxLength={128}
                minLength={1}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </div>
            <button
              className="flex w-full items-center justify-center rounded-md bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={submitting}
              type="submit"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
