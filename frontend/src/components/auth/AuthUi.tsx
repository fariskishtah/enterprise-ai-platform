import {
  useId,
  useState,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

import { useTheme } from "../../theme/ThemeContext";

export const authInputClassName =
  "mt-2 block min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2.5 text-base text-[var(--text-primary)] shadow-sm outline-none placeholder:text-[var(--text-placeholder)] focus:border-[var(--primary-action)] focus:ring-2 focus:ring-[var(--focus-ring)]/25 disabled:cursor-not-allowed disabled:bg-[var(--surface-secondary)] sm:text-sm";

export const authPrimaryButtonClassName =
  "inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-[var(--button-primary)] px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-[var(--button-primary-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] disabled:cursor-not-allowed disabled:bg-[var(--button-primary-disabled)] disabled:text-white/80";

export const authSecondaryButtonClassName =
  "inline-flex min-h-11 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 text-sm font-semibold text-[var(--text-primary)] shadow-sm hover:bg-[var(--subtle-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-60";

export const authLinkClassName =
  "font-semibold text-[var(--text-link)] underline-offset-4 hover:text-[var(--text-link-hover)] hover:underline focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]";

function BrandMark(): ReactElement {
  return (
    <span
      aria-hidden="true"
      className="grid h-9 w-9 grid-cols-2 gap-1 rounded-xl bg-white/10 p-2 ring-1 ring-white/20"
    >
      <span className="rounded-sm bg-white" />
      <span className="rounded-sm bg-violet-300" />
      <span className="rounded-sm bg-violet-300" />
      <span className="rounded-sm bg-white" />
    </span>
  );
}

export function AuthShell({
  children,
  compact = false,
}: {
  readonly children: ReactNode;
  readonly compact?: boolean;
}): ReactElement {
  const { resolvedTheme, setPreference } = useTheme();
  const nextTheme = resolvedTheme === "dark" ? "light" : "dark";

  return (
    <main className="min-h-screen bg-[var(--app-background)] text-[var(--text-primary)] lg:grid lg:grid-cols-[minmax(20rem,42fr)_minmax(28rem,58fr)]">
      <aside className="relative overflow-hidden bg-[#0b1023] px-5 py-5 text-white sm:px-8 lg:flex lg:min-h-screen lg:flex-col lg:justify-between lg:px-12 lg:py-10">
        <div
          aria-hidden="true"
          className="absolute -left-32 top-20 h-80 w-80 rounded-full bg-violet-600/25 blur-3xl"
        />
        <div
          aria-hidden="true"
          className="absolute -bottom-28 right-0 h-72 w-72 rounded-full bg-indigo-400/15 blur-3xl"
        />
        <div className="relative flex items-center gap-3">
          <BrandMark />
          <div>
            <p className="text-sm font-semibold tracking-wide">FactoryMind</p>
            <p className="text-xs text-slate-300">by FK Solutions</p>
          </div>
        </div>
        <div className="relative hidden max-w-md lg:block">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300">
            Industrial intelligence, secured
          </p>
          <h2 className="mt-4 text-4xl font-semibold leading-tight tracking-tight">
            Keep every decision connected to the factory floor.
          </h2>
          <p className="mt-5 max-w-sm text-base leading-7 text-slate-300">
            A protected workspace for operations, reliability, and AI teams to act on
            trusted manufacturing data.
          </p>
        </div>
        <div className="relative hidden items-center gap-2 text-xs text-slate-400 lg:flex">
          <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24">
            <path
              d="M7 10V8a5 5 0 0 1 10 0v2m-11 0h12v10H6V10Z"
              stroke="currentColor"
              strokeWidth="1.8"
            />
          </svg>
          Encrypted sessions · Privacy-safe recovery
        </div>
      </aside>

      <section className="flex min-h-[calc(100vh-5rem)] flex-col lg:min-h-screen">
        <div className="flex justify-end px-5 pt-4 sm:px-8 lg:px-12 lg:pt-8">
          <button
            aria-label={`Use ${nextTheme} mode`}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--subtle-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
            onClick={() => setPreference(nextTheme)}
            type="button"
          >
            {resolvedTheme === "dark" ? (
              <svg
                aria-hidden="true"
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
              >
                <path
                  d="M12 3v2m0 14v2M3 12h2m14 0h2M5.64 5.64l1.42 1.42m9.88 9.88 1.42 1.42m0-12.72-1.42 1.42M7.06 16.94l-1.42 1.42M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeWidth="1.7"
                />
              </svg>
            ) : (
              <svg
                aria-hidden="true"
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
              >
                <path
                  d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.5 8.5 0 1 0 20.2 15.1Z"
                  stroke="currentColor"
                  strokeLinejoin="round"
                  strokeWidth="1.7"
                />
              </svg>
            )}
          </button>
        </div>
        <div className="flex flex-1 items-center justify-center px-5 pb-10 pt-3 sm:px-8 lg:px-12 lg:pb-16">
          <div className={`w-full ${compact ? "max-w-md" : "max-w-lg"}`}>
            {children}
          </div>
        </div>
        <footer className="px-5 pb-6 text-center text-xs text-[var(--text-muted)] sm:px-8 lg:px-12">
          © {new Date().getFullYear()} FK Solutions · FactoryMind
        </footer>
      </section>
    </main>
  );
}

export function AuthHeader({
  eyebrow,
  title,
  description,
}: {
  readonly description: ReactNode;
  readonly eyebrow?: string;
  readonly title: string;
}): ReactElement {
  return (
    <header>
      {eyebrow ? (
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-eyebrow)]">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="text-3xl font-semibold tracking-tight text-[var(--text-primary)]">
        {title}
      </h1>
      <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
        {description}
      </p>
    </header>
  );
}

export function AuthMessage({
  children,
  tone = "info",
}: {
  readonly children: ReactNode;
  readonly tone?: "danger" | "info" | "success" | "warning";
}): ReactElement {
  const styles = {
    danger:
      "border-[var(--color-danger-200)] bg-[var(--color-danger-50)] text-[var(--color-danger-900)]",
    info: "border-[var(--color-purple-200)] bg-[var(--color-purple-50)] text-[var(--text-primary)]",
    success:
      "border-[var(--color-success-200)] bg-[var(--color-success-50)] text-[var(--color-success-800)]",
    warning:
      "border-[var(--color-warning-200)] bg-[var(--color-warning-50)] text-[var(--color-warning-900)]",
  }[tone];

  return (
    <div
      aria-live="polite"
      className={`mt-5 rounded-lg border px-4 py-3 text-sm leading-6 ${styles}`}
      role={tone === "danger" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}

interface PasswordFieldProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type"
> {
  readonly label: string;
  readonly hint?: string;
}

export function PasswordField({
  className,
  hint,
  id,
  label,
  ...props
}: PasswordFieldProps): ReactElement {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const [visible, setVisible] = useState(false);

  return (
    <div>
      <label
        className="block text-sm font-medium text-[var(--text-primary)]"
        htmlFor={inputId}
      >
        {label}
      </label>
      <div className="relative">
        <input
          {...props}
          aria-describedby={hintId}
          className={`${authInputClassName} pr-20 ${className ?? ""}`}
          id={inputId}
          type={visible ? "text" : "password"}
        />
        <button
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
          className="absolute inset-y-2 right-2 mt-2 rounded-md px-2.5 text-xs font-semibold text-[var(--text-link)] hover:bg-[var(--subtle-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]"
          onClick={() => setVisible((current) => !current)}
          type="button"
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      {hint ? (
        <p className="mt-1.5 text-xs leading-5 text-[var(--text-muted)]" id={hintId}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function PasswordGuidance({
  password,
}: {
  readonly password: string;
}): ReactElement {
  const validLength = password.length >= 12 && password.length <= 128;
  const descriptiveStrength =
    password.length === 0
      ? "Not entered"
      : password.length < 12
        ? "Needs more characters"
        : password.length < 16
          ? "Good"
          : "Strong";

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-secondary)] px-3.5 py-3">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="font-medium text-[var(--text-primary)]">
          Password strength
        </span>
        <span aria-live="polite" className="text-[var(--text-secondary)]">
          {descriptiveStrength}
        </span>
      </div>
      <div
        aria-hidden="true"
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--border)]"
      >
        <span
          className={`block h-full rounded-full transition-all ${validLength ? "bg-[var(--color-success-600)]" : "bg-[var(--primary-action)]"}`}
          style={{
            width: `${Math.min(Math.max((password.length / 16) * 100, 8), 100)}%`,
          }}
        />
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
        Use 12–128 characters. A unique passphrase is easier to remember and harder to
        guess.
      </p>
    </div>
  );
}

export function LoadingSpinner(): ReactElement {
  return (
    <svg
      aria-hidden="true"
      className="h-4 w-4 animate-spin"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-30"
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="3"
      />
      <path
        className="opacity-90"
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="3"
      />
    </svg>
  );
}
