import { useState, type FormEvent, type ReactElement } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import fkLoginBackground from "../assets/fk-login-background.png";

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
    <main className="flex min-h-screen flex-col overflow-x-hidden bg-[var(--surface)] text-neutral-950 lg:grid lg:grid-cols-[minmax(0,58fr)_minmax(25rem,42fr)]">
      <section
        aria-label="FK Solutions industrial technology"
        className="relative h-44 shrink-0 overflow-hidden bg-neutral-950 sm:h-56 md:h-64 lg:h-auto lg:min-h-screen"
      >
        <img
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-left"
          src={fkLoginBackground}
        />
        <div aria-hidden="true" className="absolute inset-0 bg-neutral-950/10" />
      </section>

      <section className="flex min-h-0 flex-1 items-center justify-center bg-[var(--surface)] px-5 py-10 sm:px-10 sm:py-12 lg:min-h-screen lg:px-12 xl:px-16">
        <div className="w-full max-w-md">
          <div className="mb-9 border-b border-neutral-200 pb-6">
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800">
              FK SOLUTIONS
            </p>
            <p className="mt-2 text-sm font-medium text-neutral-600">
              AI Manufacturing Platform
            </p>
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
                className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none transition focus:border-purple-700 focus:ring-2 focus:ring-purple-700/20"
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
                className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none transition focus:border-purple-700 focus:ring-2 focus:ring-purple-700/20"
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
              className="flex w-full items-center justify-center rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700 disabled:cursor-not-allowed"
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
