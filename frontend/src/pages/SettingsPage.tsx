import type { ReactElement } from "react";

import { useAuth } from "../auth/useAuth";
import { KeyValues, panelClassName } from "../components/intelligence/IntelligenceUi";
import { PageHeader } from "../components/ui/PageHeader";
import { useTheme, type ThemePreference } from "../theme/ThemeContext";

const themeOptions: readonly { label: string; value: ThemePreference }[] = [
  { label: "Use system setting", value: "system" },
  { label: "Light", value: "light" },
  { label: "Dark", value: "dark" },
];

export function SettingsPage(): ReactElement {
  const { user } = useAuth();
  const { preference, resolvedTheme, setPreference } = useTheme();

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
      <section className={`${panelClassName} mt-6`} aria-labelledby="security-heading">
        <h3 className="text-lg font-semibold text-foreground" id="security-heading">
          Security and workspace
        </h3>
        <p className="mt-2 text-sm leading-6 text-secondary-foreground">
          Password changes, device/session management, MFA, profile mutation, and
          default workspace preferences are not available from the current backend API.
          Deployment controls such as API documentation exposure are intentionally not
          user settings.
        </p>
      </section>
    </section>
  );
}
