import { useRef, useState, type FormEvent, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { acceptInvitation } from "../api/account";
import { ApiError } from "../api/client";
import {
  AuthHeader,
  AuthMessage,
  AuthShell,
  LoadingSpinner,
  PasswordField,
  PasswordGuidance,
  authInputClassName,
  authPrimaryButtonClassName,
  authSecondaryButtonClassName,
} from "../components/auth/AuthUi";

function invitationError(error: unknown): string {
  if (!(error instanceof ApiError))
    return "We could not accept the invitation. Check your connection and try again.";
  if (error.status === 410)
    return "This invitation has expired. Ask your workspace administrator to send a new one.";
  if (error.status === 409)
    return "This invitation was already accepted or is no longer available.";
  if (error.status === 422 || error.status === 404)
    return "This invitation link is not valid. Ask your workspace administrator for a new one.";
  if (error.status === 429) return "Too many attempts. Wait a moment, then try again.";
  return "The invitation is temporarily unavailable. Please try again.";
}

export function InvitationAcceptancePage(): ReactElement {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(
    token === null
      ? "This invitation link is not valid. Ask your workspace administrator for a new one."
      : null,
  );
  const submittingRef = useRef(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (token === null || submittingRef.current) return;
    submittingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await acceptInvitation({
        token,
        ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
        ...(password ? { password } : {}),
      });
      setAccepted(true);
    } catch (caught) {
      setError(invitationError(caught));
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  };

  if (accepted) {
    return (
      <AuthShell compact>
        <AuthHeader
          description="Your account now has the access assigned by your company."
          eyebrow="Invitation accepted"
          title="Welcome to your team"
        />
        <AuthMessage tone="success">Your FactoryMind account is ready.</AuthMessage>
        <Link className={`${authPrimaryButtonClassName} mt-7`} to="/login">
          Continue to sign in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell compact>
      <AuthHeader
        description="Accept your company invitation to join its protected FactoryMind workspace."
        eyebrow="Team invitation"
        title="Join your workspace"
      />
      <div className="mt-5 rounded-lg border border-[var(--border)] bg-[var(--surface-secondary)] p-4 text-sm leading-6 text-[var(--text-secondary)]">
        New to FactoryMind? Enter your name and create a password. Already a member of
        this company? Leave both fields empty.
      </div>
      <form className="mt-6 space-y-5" onSubmit={(event) => void submit(event)}>
        <div>
          <label
            className="block text-sm font-medium text-[var(--text-primary)]"
            htmlFor="invitation-name"
          >
            Full name{" "}
            <span className="font-normal text-[var(--text-muted)]">(new accounts)</span>
          </label>
          <input
            autoComplete="name"
            className={authInputClassName}
            disabled={busy || token === null}
            id="invitation-name"
            minLength={2}
            onChange={(event) => setFullName(event.target.value)}
            value={fullName}
          />
        </div>
        <PasswordField
          autoComplete="new-password"
          disabled={busy || token === null}
          label="Password (new accounts)"
          maxLength={128}
          minLength={12}
          onChange={(event) => setPassword(event.target.value)}
          value={password}
        />
        {password ? <PasswordGuidance password={password} /> : null}
        {error ? <AuthMessage tone="danger">{error}</AuthMessage> : null}
        <button
          className={authPrimaryButtonClassName}
          disabled={busy || token === null}
          type="submit"
        >
          {busy ? <LoadingSpinner /> : null}
          {busy ? "Joining workspace…" : "Accept invitation"}
        </button>
      </form>
      <Link className={`${authSecondaryButtonClassName} mt-3 w-full`} to="/login">
        Return to sign in
      </Link>
      <p className="mt-4 text-center text-xs text-[var(--text-muted)]">
        Need a new invitation? Contact your workspace administrator.
      </p>
    </AuthShell>
  );
}
