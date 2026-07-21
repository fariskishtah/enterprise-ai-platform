import type { RefObject, ReactElement } from "react";

import { useAuth } from "../auth/useAuth";
import { useTheme, type ThemePreference } from "../theme/ThemeContext";
import { Icon } from "./Icon";

interface TopbarProps {
  readonly menuButtonRef: RefObject<HTMLButtonElement>;
  readonly onOpenNavigation: () => void;
  readonly title: string;
}

export function Topbar({
  menuButtonRef,
  onOpenNavigation,
  title,
}: TopbarProps): ReactElement {
  const { logout, role, user } = useAuth();
  const { preference, setPreference } = useTheme();
  const initials = user?.email.slice(0, 2).toUpperCase() ?? "US";

  return (
    <header className="sticky top-0 z-20 flex h-[4.5rem] shrink-0 items-center border-b border-neutral-200 bg-neutral-50 px-4 sm:px-6 lg:px-10">
      <button
        aria-label="Open navigation"
        className="mr-3 rounded-md p-2 text-neutral-600 hover:bg-neutral-100 hover:text-neutral-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700 lg:hidden"
        onClick={onOpenNavigation}
        ref={menuButtonRef}
        type="button"
      >
        <Icon name="menu" />
      </button>

      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Workspace
        </p>
        <h1 className="truncate text-lg font-semibold tracking-tight text-foreground">
          {title}
        </h1>
      </div>

      <div className="ml-4 flex items-center gap-2 sm:gap-3">
        <label className="sr-only" htmlFor="theme-preference">
          Color theme
        </label>
        <select
          aria-label="Color theme"
          className="h-10 rounded-md border border-border-strong bg-elevated px-2 text-sm font-medium text-secondary-foreground"
          id="theme-preference"
          onChange={(event) => setPreference(event.target.value as ThemePreference)}
          title="Color theme"
          value={preference}
        >
          <option value="system">System theme</option>
          <option value="light">Light theme</option>
          <option value="dark">Dark theme</option>
        </select>
        <button
          aria-label={`Sign out ${user?.email ?? "current user"}`}
          className="flex h-10 items-center justify-center gap-2 rounded-md border border-border-strong bg-card px-2.5 text-xs font-bold text-secondary-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700"
          onClick={() => void logout()}
          title="Sign out"
          type="button"
        >
          <span
            aria-hidden="true"
            className="flex h-7 w-7 items-center justify-center rounded-md bg-neutral-900 text-[10px] text-white"
          >
            {initials}
          </span>
          <span className="hidden min-w-0 text-left sm:block">
            <span className="block max-w-40 truncate text-sm font-medium">
              {user?.email}
            </span>
            <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {role}
            </span>
          </span>
        </button>
      </div>
    </header>
  );
}
