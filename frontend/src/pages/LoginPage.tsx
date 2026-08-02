import { useRef, useState, type FormEvent, type ReactElement } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import {
  AuthHeader,
  AuthMessage,
  AuthShell,
  LoadingSpinner,
  PasswordField,
  authInputClassName,
  authLinkClassName,
  authPrimaryButtonClassName,
} from "../components/auth/AuthUi";

interface LoginLocationState {
  readonly from?: string;
}

function loginError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "We could not sign you in. Check your connection and try again.";
  }
  if (error.status === 401 || error.status === 422) {
    return "The email or password you entered is not correct.";
  }
  if (error.status === 403) {
    return "This account is not available. Contact your workspace administrator.";
  }
  if (error.status === 429) {
    return "Too many sign-in attempts. Wait a moment, then try again.";
  }
  return "Sign in is temporarily unavailable. Please try again.";
}

export function LoginPage(): ReactElement {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const requestedDestination = (location.state as LoginLocationState | null)?.from;
  const destination =
    requestedDestination?.startsWith("/") === true &&
    !requestedDestination.startsWith("//")
      ? requestedDestination
      : "/";
  const notice =
    auth.notice ??
    (searchParams.get("reason") === "session-expired"
      ? "Your session expired. Please sign in again."
      : null);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setError(null);
    auth.clearNotice();
    setSubmitting(true);
    try {
      await auth.login({ email: email.trim(), password });
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(loginError(caught));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <AuthShell compact>
      <AuthHeader
        description="Access your manufacturing intelligence workspace with your work account."
        eyebrow="Secure workspace"
        title="Welcome back"
      />

      {notice !== null ? <AuthMessage tone="warning">{notice}</AuthMessage> : null}
      {error !== null ? <AuthMessage tone="danger">{error}</AuthMessage> : null}

      <form
        className="mt-7 space-y-5"
        noValidate
        onSubmit={(event) => void submit(event)}
      >
        <div>
          <label
            className="block text-sm font-medium text-[var(--text-primary)]"
            htmlFor="login-email"
          >
            Work email
          </label>
          <input
            autoCapitalize="none"
            autoComplete="email"
            autoCorrect="off"
            className={authInputClassName}
            disabled={submitting}
            id="login-email"
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
          autoComplete="current-password"
          disabled={submitting}
          label="Password"
          maxLength={128}
          minLength={1}
          onChange={(event) => setPassword(event.target.value)}
          required
          value={password}
        />
        <div className="flex justify-end">
          <Link className={`text-sm ${authLinkClassName}`} to="/forgot-password">
            Forgot password?
          </Link>
        </div>
        <button
          className={authPrimaryButtonClassName}
          disabled={submitting}
          type="submit"
        >
          {submitting ? <LoadingSpinner /> : null}
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-7 text-center text-sm text-[var(--text-secondary)]">
        New to FactoryMind?{" "}
        <Link className={authLinkClassName} to="/register">
          Create a workspace
        </Link>
      </p>
      <p className="mt-3 text-center text-xs text-[var(--text-muted)]">
        Protected by encrypted session cookies and automatic session rotation.
      </p>
    </AuthShell>
  );
}
