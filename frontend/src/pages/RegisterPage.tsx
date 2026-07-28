import { useState, type FormEvent, type ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import fkLoginBackground from "../assets/fk-login-background.webp";
import { useAuth } from "../auth/useAuth";

export function RegisterPage(): ReactElement {
  const auth = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      const localToken = await auth.register({
        company_name: companyName,
        email,
        name,
        password,
      });
      navigate(
        localToken === null
          ? "/verify-email"
          : `/verify-email?token=${encodeURIComponent(localToken)}`,
        { replace: true },
      );
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Account creation failed. Please try again.",
      );
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col overflow-x-hidden bg-[var(--surface)] text-neutral-950 lg:grid lg:grid-cols-[minmax(0,55fr)_minmax(28rem,45fr)]">
      <section
        aria-label="FK Solutions industrial technology"
        className="relative h-36 shrink-0 overflow-hidden bg-neutral-950 sm:h-48 lg:h-auto lg:min-h-screen"
      >
        <img
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-left"
          src={fkLoginBackground}
        />
        <div aria-hidden="true" className="absolute inset-0 bg-neutral-950/10" />
      </section>

      <section className="flex min-h-0 flex-1 items-center justify-center bg-[var(--surface)] px-5 py-8 sm:px-10 lg:min-h-screen lg:px-12">
        <div className="w-full max-w-lg">
          <div className="mb-7 border-b border-neutral-200 pb-5">
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800">
              FK SOLUTIONS
            </p>
            <p className="mt-2 text-sm font-medium text-neutral-600">
              AI Manufacturing Platform
            </p>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Create your AI manufacturing workspace
          </h1>
          <p className="mt-2 text-sm leading-6 text-neutral-600">
            Start managing your factory intelligence platform.
          </p>

          {error === null ? null : (
            <div
              className="mt-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {error}
            </div>
          )}

          <form className="mt-5 space-y-4" onSubmit={(event) => void submit(event)}>
            <label className="block text-sm font-medium text-neutral-800">
              Full name
              <input
                autoComplete="name"
                className="mt-1.5 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm"
                disabled={submitting}
                maxLength={160}
                minLength={2}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </label>
            <label className="block text-sm font-medium text-neutral-800">
              Company name
              <input
                autoComplete="organization"
                className="mt-1.5 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm"
                disabled={submitting}
                maxLength={255}
                minLength={2}
                onChange={(event) => setCompanyName(event.target.value)}
                required
                value={companyName}
              />
            </label>
            <label className="block text-sm font-medium text-neutral-800">
              Work email
              <input
                autoComplete="email"
                className="mt-1.5 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm"
                disabled={submitting}
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block text-sm font-medium text-neutral-800">
                Password
                <input
                  autoComplete="new-password"
                  className="mt-1.5 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm"
                  disabled={submitting}
                  maxLength={128}
                  minLength={12}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  type="password"
                  value={password}
                />
              </label>
              <label className="block text-sm font-medium text-neutral-800">
                Confirm password
                <input
                  autoComplete="new-password"
                  className="mt-1.5 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm"
                  disabled={submitting}
                  maxLength={128}
                  minLength={12}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                  type="password"
                  value={confirmPassword}
                />
              </label>
            </div>
            <p className="text-xs leading-5 text-neutral-600">
              Use at least 12 characters with uppercase, lowercase, number, and symbol.
            </p>
            {submitting ? (
              <p aria-live="polite" className="text-sm text-purple-800" role="status">
                Your AI manufacturing workspace is being prepared.
              </p>
            ) : null}
            <button
              className="flex w-full items-center justify-center rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700 disabled:cursor-not-allowed disabled:opacity-70"
              disabled={submitting}
              type="submit"
            >
              {submitting ? "Preparing workspace…" : "Create your workspace"}
            </button>
          </form>
          <p className="mt-5 text-center text-sm text-neutral-600">
            Already have an account?{" "}
            <Link
              className="font-semibold text-purple-800 underline-offset-4 hover:underline"
              to="/login"
            >
              Sign in
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
