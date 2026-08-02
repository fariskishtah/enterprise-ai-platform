import { useEffect, useRef, useState, type FormEvent, type ReactElement } from "react";
import { Link } from "react-router-dom";
import {
  changePassword,
  listSessions,
  revokeActiveSession,
  revokeOtherSessions,
  type ActiveSession,
} from "../api/account";
import { ApiError, isRequestCancelled } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { hasLegacyRoleAccess } from "../auth/permissions";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../components/hierarchy/ResourceStates";
import { KeyValues, panelClassName } from "../components/intelligence/IntelligenceUi";
import { formatDate } from "../components/intelligence/IntelligenceUi";
import { PageHeader } from "../components/ui/PageHeader";
import { PasswordField, PasswordGuidance } from "../components/auth/AuthUi";
import { useTheme, type ThemePreference } from "../theme/ThemeContext";

const themeOptions: readonly { label: string; value: ThemePreference }[] = [
  { label: "Use system setting", value: "system" },
  { label: "Light", value: "light" },
  { label: "Dark", value: "dark" },
];

export function SettingsPage(): ReactElement {
  const { logout, user } = useAuth();
  const { preference, resolvedTheme, setPreference } = useTheme();
  const [sessions, setSessions] = useState<readonly ActiveSession[]>([]);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const passwordRequestRef = useRef(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listSessions(controller.signal)
      .then((value) => {
        setSessions(value.items);
        setSessionError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setSessionError(
            caught instanceof Error ? caught.message : "Sessions unavailable.",
          );
      });
    return () => controller.abort();
  }, [revision]);

  const submitPassword = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (passwordRequestRef.current) return;
    if (newPassword.length < 12 || newPassword.length > 128) {
      setPasswordError("Use a new password between 12 and 128 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New password confirmation does not match.");
      return;
    }
    passwordRequestRef.current = true;
    setBusy(true);
    setPasswordError(null);
    void changePassword({
      current_password: currentPassword,
      new_password: newPassword,
    })
      .then(async () => {
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setMessage("Password changed. Sign in again with the new password.");
        await logout();
      })
      .catch((caught: unknown) =>
        setPasswordError(
          caught instanceof ApiError && caught.status === 422
            ? "The current password is incorrect, or the new password is not allowed."
            : "The password could not be changed. Please try again.",
        ),
      )
      .finally(() => {
        passwordRequestRef.current = false;
        setBusy(false);
      });
  };

  return (
    <section>
      <PageHeader
        eyebrow="Account"
        headingId="settings-heading"
        title="Settings"
        description="Personal display preferences and account information supported by the current platform."
      />
      {user && hasLegacyRoleAccess(user.role, ["admin"]) ? (
        <section
          className={`${panelClassName} mt-6 flex flex-wrap items-center justify-between gap-4`}
          aria-labelledby="billing-settings-heading"
        >
          <div>
            <h3
              className="text-lg font-semibold text-foreground"
              id="billing-settings-heading"
            >
              Billing & subscription
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Review your plan, workspace limits, usage, payments, and invoices.
            </p>
          </div>
          <Link className={primaryButtonClassName} to="/settings/billing">
            Manage billing
          </Link>
        </section>
      ) : null}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className={panelClassName} aria-labelledby="appearance-heading">
          <h3 className="text-lg font-semibold text-foreground" id="appearance-heading">
            Appearance
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Theme preference is saved in this browser and applies immediately.
          </p>
          <fieldset className="mt-5 space-y-3">
            <legend className="sr-only">Color theme</legend>
            {themeOptions.map((option) => (
              <label
                className="flex cursor-pointer items-center gap-3 rounded-md border border-border bg-elevated p-3 text-sm font-medium text-foreground"
                key={option.value}
              >
                <input
                  checked={preference === option.value}
                  name="theme"
                  onChange={() => setPreference(option.value)}
                  type="radio"
                  value={option.value}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          <p className="mt-4 text-xs text-muted-foreground">
            Currently rendered in {resolvedTheme} mode. No server save is required.
          </p>
        </section>

        <section className={panelClassName} aria-labelledby="profile-heading">
          <h3 className="text-lg font-semibold text-foreground" id="profile-heading">
            Profile
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            The backend currently exposes account information as read-only.
          </p>
          <div className="mt-5">
            <KeyValues
              items={[
                { label: "Email", value: user?.email ?? "Unavailable" },
                { label: "Role", value: user?.role ?? "Unavailable" },
                { label: "Company ID", value: user?.company_id ?? "Unavailable" },
                {
                  label: "Account status",
                  value: user?.is_active ? "Active" : "Inactive",
                },
                { label: "User ID", value: user?.id ?? "Unavailable" },
              ]}
            />
          </div>
        </section>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section
          className={panelClassName}
          aria-labelledby="password-heading"
          id="change-password"
        >
          <h3 className="text-lg font-semibold text-foreground" id="password-heading">
            Change password
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Changing your password revokes all refresh sessions.
          </p>
          <form className="mt-5 space-y-4" onSubmit={submitPassword}>
            <PasswordField
              autoComplete="current-password"
              disabled={busy}
              label="Current password"
              maxLength={128}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              value={currentPassword}
            />
            <PasswordField
              autoComplete="new-password"
              disabled={busy}
              label="New password"
              maxLength={128}
              minLength={12}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              value={newPassword}
            />
            <PasswordGuidance password={newPassword} />
            <PasswordField
              aria-invalid={
                confirmPassword.length > 0 && newPassword !== confirmPassword
              }
              autoComplete="new-password"
              disabled={busy}
              hint={
                confirmPassword.length > 0 && newPassword !== confirmPassword
                  ? "The two passwords do not match yet."
                  : undefined
              }
              label="Confirm new password"
              maxLength={128}
              minLength={12}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              value={confirmPassword}
            />
            {passwordError ? (
              <p className="text-sm text-red-700" role="alert">
                {passwordError}
              </p>
            ) : null}
            {message ? (
              <p className="text-sm text-emerald-700" role="status">
                {message}
              </p>
            ) : null}
            <button className={primaryButtonClassName} disabled={busy} type="submit">
              {busy ? "Changing…" : "Change password"}
            </button>
          </form>
        </section>
        <section className={panelClassName} aria-labelledby="sessions-heading">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3
                className="text-lg font-semibold text-foreground"
                id="sessions-heading"
              >
                Active sessions
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Refresh sessions currently authorized for this account.
              </p>
            </div>
            <button
              className={secondaryButtonClassName}
              onClick={() => {
                setSessionError(null);
                void revokeOtherSessions()
                  .then(() => {
                    setMessage("Other sessions revoked.");
                    setRevision((value) => value + 1);
                  })
                  .catch((caught: unknown) =>
                    setSessionError(
                      caught instanceof Error
                        ? caught.message
                        : "Sessions could not be revoked.",
                    ),
                  );
              }}
              type="button"
            >
              Revoke other sessions
            </button>
          </div>
          {sessionError ? (
            <p className="mt-4 text-sm text-red-700" role="alert">
              {sessionError}
            </p>
          ) : null}
          <ul className="mt-5 space-y-3">
            {sessions.map((session) => (
              <li
                className="rounded-md border border-border bg-elevated p-4"
                key={session.id}
              >
                <p className="font-medium text-foreground">
                  {session.user_agent_summary ?? "Unknown client"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Created {formatDate(session.created_at)} · Expires{" "}
                  {formatDate(session.expires_at)} · IP{" "}
                  {session.source_ip ?? "Unavailable"}
                </p>
                <button
                  className="mt-3 text-sm font-semibold text-red-700"
                  onClick={() => {
                    void revokeActiveSession(session.id)
                      .then(() => setRevision((value) => value + 1))
                      .catch((caught: unknown) =>
                        setSessionError(
                          caught instanceof Error
                            ? caught.message
                            : "Session could not be revoked.",
                        ),
                      );
                  }}
                  type="button"
                >
                  Revoke session
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section className={`${panelClassName} mt-6`}>
        <h3 className="text-lg font-semibold text-foreground">Identity and access</h3>
        <p className="mt-2 text-sm text-secondary-foreground">
          Contact your company administrator to change role assignments or account
          access. Enterprise federation options are managed by your deployment owner.
        </p>
      </section>
    </section>
  );
}
