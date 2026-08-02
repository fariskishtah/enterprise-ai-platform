import { useRef, useState, type FormEvent, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { completePasswordReset, requestPasswordReset } from "../auth/authApi";
import {
  AuthHeader,
  AuthMessage,
  AuthShell,
  LoadingSpinner,
  PasswordField,
  PasswordGuidance,
  authInputClassName,
  authLinkClassName,
  authPrimaryButtonClassName,
  authSecondaryButtonClassName,
} from "../components/auth/AuthUi";

const resetConfirmation =
  "If an account matches that email, we’ll send a password reset link shortly.";

type ResetState = "expired" | "form" | "invalid" | "success" | "used";

function resetFailureState(error: unknown): Exclude<ResetState, "form" | "success"> {
  if (error instanceof ApiError && error.status === 410) return "expired";
  if (error instanceof ApiError && error.status === 409) return "used";
  return "invalid";
}

export function ForgotPasswordPage(): ReactElement {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [localToken, setLocalToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submittingRef = useRef(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await requestPasswordReset(email.trim());
      setLocalToken(response.local_reset_token);
      setSubmitted(true);
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 429
          ? "Too many reset requests. Wait a few minutes, then try again."
          : "We could not submit the request. Check your connection and try again.",
      );
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  };

  return (
    <AuthShell compact>
      {submitted ? (
        <>
          <AuthHeader
            description="For your privacy, this confirmation is the same for every email address."
            eyebrow="Request received"
            title="Check your inbox"
          />
          <AuthMessage tone="success">{resetConfirmation}</AuthMessage>
          <div className="mt-6 rounded-lg border border-[var(--border)] bg-[var(--surface-secondary)] p-4 text-sm leading-6 text-[var(--text-secondary)]">
            The link expires in 30 minutes and can be used once. Check your spam folder
            if it does not arrive after a few minutes.
          </div>
          {localToken ? (
            <Link
              className={`${authPrimaryButtonClassName} mt-6`}
              to={`/reset-password?token=${encodeURIComponent(localToken)}`}
            >
              Continue with local test link
            </Link>
          ) : null}
          <Link className={`${authSecondaryButtonClassName} mt-3 w-full`} to="/login">
            Return to sign in
          </Link>
          <button
            className={`mx-auto mt-5 block text-sm ${authLinkClassName}`}
            onClick={() => {
              setSubmitted(false);
              setLocalToken(null);
            }}
            type="button"
          >
            Try another email
          </button>
        </>
      ) : (
        <>
          <AuthHeader
            description="Enter your work email. We’ll send a secure reset link if it matches an account."
            eyebrow="Account recovery"
            title="Reset your password"
          />
          {error ? <AuthMessage tone="danger">{error}</AuthMessage> : null}
          <form className="mt-7 space-y-5" onSubmit={(event) => void submit(event)}>
            <div>
              <label
                className="block text-sm font-medium text-[var(--text-primary)]"
                htmlFor="recovery-email"
              >
                Work email
              </label>
              <input
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect="off"
                className={authInputClassName}
                disabled={busy}
                id="recovery-email"
                inputMode="email"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@company.com"
                required
                spellCheck={false}
                type="email"
                value={email}
              />
            </div>
            <button
              className={authPrimaryButtonClassName}
              disabled={busy}
              type="submit"
            >
              {busy ? <LoadingSpinner /> : null}
              {busy ? "Sending secure link…" : "Send reset link"}
            </button>
          </form>
          <Link
            className={`mt-6 inline-block text-sm ${authLinkClassName}`}
            to="/login"
          >
            ← Back to sign in
          </Link>
        </>
      )}
    </AuthShell>
  );
}

const resetCopy: Record<
  Exclude<ResetState, "form" | "success">,
  { title: string; description: string }
> = {
  expired: {
    title: "This reset link has expired",
    description:
      "Reset links expire after 30 minutes to protect your account. Request a new link to continue.",
  },
  invalid: {
    title: "This reset link is not valid",
    description:
      "The link may be incomplete or no longer recognized. Request a new secure link to continue.",
  },
  used: {
    title: "This reset link was already used",
    description:
      "Each reset link works once. If you still cannot sign in, request a new link.",
  },
};

export function ResetPasswordPage(): ReactElement {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [state, setState] = useState<ResetState>(
    token.length >= 32 ? "form" : "invalid",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submittingRef = useRef(false);
  const passwordValid = password.length >= 12 && password.length <= 128;
  const mismatch = confirmation.length > 0 && password !== confirmation;

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submittingRef.current) return;
    setError(null);
    if (!passwordValid) {
      setError("Use a password between 12 and 128 characters.");
      return;
    }
    if (password !== confirmation) {
      setError("The password confirmation does not match.");
      return;
    }
    submittingRef.current = true;
    setBusy(true);
    try {
      await completePasswordReset(token, password);
      setState("success");
    } catch (caught) {
      setState(resetFailureState(caught));
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  };

  if (state === "success") {
    return (
      <AuthShell compact>
        <AuthHeader
          description="Your password is updated and all previous sessions have been signed out."
          eyebrow="Password secured"
          title="You’re ready to sign in"
        />
        <AuthMessage tone="success">
          Use your new password the next time you sign in to FactoryMind.
        </AuthMessage>
        <Link className={`${authPrimaryButtonClassName} mt-6`} to="/login">
          Continue to sign in
        </Link>
      </AuthShell>
    );
  }

  if (state !== "form") {
    return (
      <AuthShell compact>
        <AuthHeader
          description={resetCopy[state].description}
          eyebrow="Recovery link"
          title={resetCopy[state].title}
        />
        <Link className={`${authPrimaryButtonClassName} mt-7`} to="/forgot-password">
          Request a new reset link
        </Link>
        <Link className={`${authSecondaryButtonClassName} mt-3 w-full`} to="/login">
          Return to sign in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell compact>
      <AuthHeader
        description="Choose a unique password for your FactoryMind account. Saving it signs out all existing sessions."
        eyebrow="Secure account recovery"
        title="Create a new password"
      />
      <form
        className="mt-7 space-y-5"
        noValidate
        onSubmit={(event) => void submit(event)}
      >
        <PasswordField
          autoComplete="new-password"
          disabled={busy}
          label="New password"
          maxLength={128}
          minLength={12}
          onChange={(event) => setPassword(event.target.value)}
          required
          value={password}
        />
        <PasswordGuidance password={password} />
        <PasswordField
          aria-invalid={mismatch}
          autoComplete="new-password"
          disabled={busy}
          hint={mismatch ? "The two passwords do not match yet." : undefined}
          label="Confirm new password"
          maxLength={128}
          minLength={12}
          onChange={(event) => setConfirmation(event.target.value)}
          required
          value={confirmation}
        />
        {error ? <AuthMessage tone="danger">{error}</AuthMessage> : null}
        <button className={authPrimaryButtonClassName} disabled={busy} type="submit">
          {busy ? <LoadingSpinner /> : null}
          {busy ? "Securing account…" : "Save new password"}
        </button>
      </form>
      <Link className={`mt-6 inline-block text-sm ${authLinkClassName}`} to="/login">
        Cancel and return to sign in
      </Link>
    </AuthShell>
  );
}
