import type { RefObject, ReactElement } from "react";

import { useAuth } from "../auth/useAuth";
import { Icon } from "./Icon";

interface TopbarProps {
  readonly menuButtonRef: RefObject<HTMLButtonElement>;
  readonly onOpenNavigation: () => void;
  readonly title: string;
}

const PLACEHOLDER_CONTEXT = "Northstar · Alexandria";

export function Topbar({
  menuButtonRef,
  onOpenNavigation,
  title,
}: TopbarProps): ReactElement {
  const { logout, role, user } = useAuth();
  const initials = user?.email.slice(0, 2).toUpperCase() ?? "US";

  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center border-b border-neutral-200 bg-white px-4 sm:px-6 lg:px-8">
      <button
        aria-label="Open navigation"
        className="mr-3 rounded-md p-2 text-neutral-600 hover:bg-neutral-100 hover:text-neutral-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 lg:hidden"
        onClick={onOpenNavigation}
        ref={menuButtonRef}
        type="button"
      >
        <Icon name="menu" />
      </button>

      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium uppercase tracking-wider text-neutral-500">
          Workspace
        </p>
        <h1 className="truncate text-lg font-semibold text-neutral-950">{title}</h1>
      </div>

      <div className="ml-4 flex items-center gap-2 sm:gap-3">
        <button
          aria-label={`Manufacturing context: ${PLACEHOLDER_CONTEXT}. Selection is not available yet.`}
          className="hidden max-w-56 items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 sm:flex"
          title="Context selection will be available in a later phase"
          type="button"
        >
          <span className="truncate">{PLACEHOLDER_CONTEXT}</span>
          <span aria-hidden="true" className="text-neutral-400">
            ⌄
          </span>
        </button>
        <button
          aria-label={`Sign out ${user?.email ?? "current user"}`}
          className="flex h-9 items-center justify-center gap-2 rounded-md border border-neutral-200 bg-neutral-100 px-2.5 text-xs font-bold text-neutral-700 hover:bg-neutral-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
          onClick={() => void logout()}
          title="Sign out"
          type="button"
        >
          <span
            aria-hidden="true"
            className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-700 text-[10px] text-white"
          >
            {initials}
          </span>
          <span className="hidden min-w-0 text-left sm:block">
            <span className="block max-w-40 truncate text-sm font-medium">
              {user?.email}
            </span>
            <span className="block text-[10px] font-medium uppercase tracking-wider text-neutral-500">
              {role}
            </span>
          </span>
        </button>
      </div>
    </header>
  );
}
