import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import {
  changePassword,
  listSessions,
  revokeActiveSession,
  revokeOtherSessions,
  type ActiveSession,
} from "../api/account";
import { isRequestCancelled } from "../api/client";
import { readStoredTokens } from "../api/sessionStorage";
import { useAuth } from "../auth/useAuth";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../components/hierarchy/ResourceStates";
import { KeyValues, panelClassName } from "../components/intelligence/IntelligenceUi";
import { formatDate, inputClassName } from "../components/intelligence/IntelligenceUi";
import { PageHeader } from "../components/ui/PageHeader";
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
  const [busy, setBusy] = useState(false);
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
    const form = event.currentTarget;
    const data = new FormData(form);
    const newPassword = String(data.get("newPassword"));
    if (newPassword !== String(data.get("confirmPassword"))) {
      setPasswordError("New password confirmation does not match.");
      return;
    }
    setBusy(true);
    setPasswordError(null);
    void changePassword({
      current_password: String(data.get("currentPassword")),
      new_password: newPassword,
    })
      .then(async () => {
        form.reset();
        setMessage("Password changed. Sign in again with the new password.");
        await logout();
      })
      .catch((caught: unknown) =>
        setPasswordError(
          caught instanceof Error ? caught.message : "Password could not be changed.",
        ),
      )
      .finally(() => setBusy(false));
  };

  return (
    <section>
      <PageHeader
        eyebrow="Account"
        headingId="settings-heading"
        title="Settings"
        description="Personal display preferences and account information supported by the current platform."
      />
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
        <section className={panelClassName} aria-labelledby="password-heading">
          <h3 className="text-lg font-semibold text-foreground" id="password-heading">
            Change password
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Changing your password revokes all refresh sessions.
          </p>
          <form className="mt-5 space-y-4" onSubmit={submitPassword}>
            <label className="block text-sm font-medium">
              Current password
              <input
                className={inputClassName}
                name="currentPassword"
                required
                type="password"
              />
            </label>
            <label className="block text-sm font-medium">
              New password
              <input
                className={inputClassName}
                minLength={12}
                name="newPassword"
                required
                type="password"
              />
            </label>
            <label className="block text-sm font-medium">
              Confirm new password
              <input
                className={inputClassName}
                minLength={12}
                name="confirmPassword"
                required
                type="password"
              />
            </label>
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
                const token = readStoredTokens()?.refreshToken;
                if (!token) return;
                setSessionError(null);
                void revokeOtherSessions(token)
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
        <h3 className="text-lg font-semibold text-foreground">
          Enterprise identity limitations
        </h3>
        <p className="mt-2 text-sm text-secondary-foreground">
          MFA, OIDC/SAML SSO, and SCIM provisioning are not included in the controlled
          pilot.
        </p>
      </section>
    </section>
  );
}
