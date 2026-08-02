import { useRef, useState, type FormEvent, type ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
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
} from "../components/auth/AuthUi";

function registrationError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "We could not create the workspace. Check your connection and try again.";
  }
  if (error.status === 409) {
    return "An account or workspace already uses these details. Try signing in, or use a different work email and company name.";
  }
  if (error.status === 429) {
    return "Too many registration attempts. Wait a moment, then try again.";
  }
  if (error.status === 422) {
    return "Review the highlighted details and make sure your password has at least 12 characters.";
  }
  return "Workspace creation is temporarily unavailable. Please try again.";
}

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
  const submittingRef = useRef(false);
  const mismatch = confirmPassword.length > 0 && password !== confirmPassword;

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submittingRef.current) return;
    setError(null);
    if (password.length < 12 || password.length > 128) {
      setError("Use a password between 12 and 128 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("The password confirmation does not match.");
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    try {
      const localToken = await auth.register({
        company_name: companyName.trim(),
        email: email.trim(),
        name: name.trim(),
        password,
      });
      navigate(
        localToken === null
          ? "/verify-email"
          : `/verify-email?token=${encodeURIComponent(localToken)}`,
        { replace: true },
      );
    } catch (caught) {
      setError(registrationError(caught));
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <AuthHeader
        description="Create the protected workspace your operations team will use to monitor assets, decisions, and AI workflows."
        eyebrow="Start with FactoryMind"
        title="Create your workspace"
      />
      {error ? (
        <AuthMessage tone="danger">
          {error}{" "}
          {error.startsWith("An account") ? (
            <Link className={authLinkClassName} to="/login">
              Sign in instead
            </Link>
          ) : null}
        </AuthMessage>
      ) : null}
      <form
        className="mt-7 space-y-5"
        noValidate
        onSubmit={(event) => void submit(event)}
      >
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label
              className="block text-sm font-medium text-[var(--text-primary)]"
              htmlFor="register-name"
            >
              Full name
            </label>
            <input
              autoComplete="name"
              className={authInputClassName}
              disabled={submitting}
              id="register-name"
              maxLength={160}
              minLength={2}
              onChange={(event) => setName(event.target.value)}
              placeholder="Your name"
              required
              value={name}
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-[var(--text-primary)]"
              htmlFor="register-company"
            >
              Company name
            </label>
            <input
              autoComplete="organization"
              className={authInputClassName}
              disabled={submitting}
              id="register-company"
              maxLength={255}
              minLength={2}
              onChange={(event) => setCompanyName(event.target.value)}
              placeholder="Company"
              required
              value={companyName}
            />
          </div>
        </div>
        <div>
          <label
            className="block text-sm font-medium text-[var(--text-primary)]"
            htmlFor="register-email"
          >
            Work email
          </label>
          <input
            autoCapitalize="none"
            autoComplete="email"
            autoCorrect="off"
            className={authInputClassName}
            disabled={submitting}
            id="register-email"
            inputMode="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@company.com"
            required
            spellCheck={false}
            type="email"
            value={email}
          />
        </div>
        <PasswordField
          autoComplete="new-password"
          disabled={submitting}
          label="Password"
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
          disabled={submitting}
          hint={mismatch ? "The two passwords do not match yet." : undefined}
          label="Confirm password"
          maxLength={128}
          minLength={12}
          onChange={(event) => setConfirmPassword(event.target.value)}
          required
          value={confirmPassword}
        />
        <p className="text-xs leading-5 text-[var(--text-muted)]">
          Review the{" "}
          <Link className={authLinkClassName} to="/legal/terms">
            Terms
          </Link>{" "}
          and{" "}
          <Link className={authLinkClassName} to="/legal/privacy">
            Privacy policy
          </Link>
          . Legal acceptance is not collected in this release.
        </p>
        <button
          className={authPrimaryButtonClassName}
          disabled={submitting}
          type="submit"
        >
          {submitting ? <LoadingSpinner /> : null}
          {submitting ? "Creating secure workspace…" : "Create workspace"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-[var(--text-secondary)]">
        Already have an account?{" "}
        <Link className={authLinkClassName} to="/login">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
