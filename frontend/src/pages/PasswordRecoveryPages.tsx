import { useState, type FormEvent, type ReactElement, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { completePasswordReset, requestPasswordReset } from "../auth/authApi";
import fkLoginBackground from "../assets/fk-login-background.webp";

const inputClassName =
  "mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none transition focus:border-purple-700 focus:ring-2 focus:ring-purple-700/20 disabled:bg-neutral-100";

function RecoveryLayout({ children }: { readonly children: ReactNode }): ReactElement {
  return (
    <main className="flex min-h-screen flex-col bg-white text-neutral-950 lg:grid lg:grid-cols-[minmax(0,52fr)_minmax(26rem,48fr)]">
      <section
        aria-label="FK Solutions industrial technology"
        className="relative h-40 overflow-hidden bg-neutral-950 sm:h-52 lg:h-auto"
      >
        <img
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          src={fkLoginBackground}
        />
        <div aria-hidden="true" className="absolute inset-0 bg-neutral-950/10" />
      </section>
      <section className="flex items-center justify-center px-5 py-10 sm:px-10 lg:min-h-screen">
        <div className="w-full max-w-md">
          <div className="mb-8 border-b border-neutral-200 pb-5">
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800">
              FK SOLUTIONS
            </p>
            <p className="mt-2 text-sm font-medium text-neutral-600">
              AI Manufacturing Platform
            </p>
          </div>
          {children}
        </div>
      </section>
    </main>
  );
}

function Message({
  children,
  error = false,
}: {
  readonly children: ReactNode;
  readonly error?: boolean;
}): ReactElement {
  return (
    <div
      className={`mt-5 rounded-md border px-4 py-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-900"}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}

export function ForgotPasswordPage(): ReactElement {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [localToken, setLocalToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await requestPasswordReset(email);
      setMessage(response.message);
      setLocalToken(response.local_reset_token);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The request could not be completed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <RecoveryLayout>
      <h1 className="text-2xl font-semibold tracking-tight">Reset your password</h1>
      <p className="mt-2 text-sm leading-6 text-neutral-600">
        Enter your work email. If an account matches, we will send reset instructions.
      </p>
      {message ? <Message>{message}</Message> : null}
      {error ? <Message error>{error}</Message> : null}
      {localToken ? (
        <Message>
          Development delivery captured.{" "}
          <Link
            className="font-semibold underline"
            to={`/reset-password?token=${encodeURIComponent(localToken)}`}
          >
            Continue to reset
          </Link>
          .
        </Message>
      ) : null}
      <form className="mt-6 space-y-5" onSubmit={(event) => void submit(event)}>
        <label
          className="block text-sm font-medium text-neutral-800"
          htmlFor="recovery-email"
        >
          Work email
        </label>
        <input
          autoComplete="email"
          className={inputClassName}
          disabled={busy}
          id="recovery-email"
          onChange={(event) => setEmail(event.target.value)}
          required
          type="email"
          value={email}
        />
        <button
          className="w-full rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700 disabled:cursor-not-allowed disabled:opacity-70"
          disabled={busy}
          type="submit"
        >
          {busy ? "Submitting…" : "Send reset instructions"}
        </button>
      </form>
      <Link
        className="mt-6 inline-block text-sm font-semibold text-purple-800 underline-offset-4 hover:underline"
        to="/login"
      >
        Back to sign in
      </Link>
    </RecoveryLayout>
  );
}

export function ResetPasswordPage(): ReactElement {
  const [searchParams] = useSearchParams();
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (busy) return;
    setError(null);
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await completePasswordReset(token, password);
      setComplete(true);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The password could not be reset. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <RecoveryLayout>
      <h1 className="text-2xl font-semibold tracking-tight">Choose a new password</h1>
      <p className="mt-2 text-sm leading-6 text-neutral-600">
        Reset links are single-use and expire. Completing this form revokes existing
        sessions.
      </p>
      {complete ? (
        <Message>
          Password updated.{" "}
          <Link className="font-semibold underline" to="/login">
            Sign in with your new password
          </Link>
          .
        </Message>
      ) : (
        <form className="mt-6 space-y-4" onSubmit={(event) => void submit(event)}>
          <label className="block text-sm font-medium text-neutral-800">
            Reset token
            <input
              autoComplete="off"
              className={inputClassName}
              disabled={busy}
              minLength={32}
              onChange={(event) => setToken(event.target.value)}
              required
              value={token}
            />
          </label>
          <label className="block text-sm font-medium text-neutral-800">
            New password
            <input
              autoComplete="new-password"
              className={inputClassName}
              disabled={busy}
              maxLength={128}
              minLength={12}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <label className="block text-sm font-medium text-neutral-800">
            Confirm new password
            <input
              autoComplete="new-password"
              className={inputClassName}
              disabled={busy}
              maxLength={128}
              minLength={12}
              onChange={(event) => setConfirmation(event.target.value)}
              required
              type="password"
              value={confirmation}
            />
          </label>
          <p className="text-xs leading-5 text-neutral-600">
            Use at least 12 characters with uppercase, lowercase, number, and symbol.
          </p>
          {error ? <Message error>{error}</Message> : null}
          <button
            className="w-full rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={busy}
            type="submit"
          >
            {busy ? "Updating…" : "Update password"}
          </button>
        </form>
      )}
      {!complete ? (
        <Link
          className="mt-6 inline-block text-sm font-semibold text-purple-800 underline-offset-4 hover:underline"
          to="/login"
        >
          Back to sign in
        </Link>
      ) : null}
    </RecoveryLayout>
  );
}
