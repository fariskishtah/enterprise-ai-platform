import type { RefObject, ReactElement } from "react";
import { NavLink } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { navigationItems } from "../navigation";
import { Icon } from "./Icon";

interface SidebarProps {
  readonly closeButtonRef?: RefObject<HTMLButtonElement>;
  readonly collapsed?: boolean;
  readonly mobile?: boolean;
  readonly onClose?: () => void;
  readonly onNavigate?: () => void;
  readonly onToggleCollapsed?: () => void;
}

export function Sidebar({
  closeButtonRef,
  collapsed = false,
  mobile = false,
  onClose,
  onNavigate,
  onToggleCollapsed,
}: SidebarProps): ReactElement {
  const { role } = useAuth();
  const visibleNavigationItems = navigationItems.filter(
    (item) => item.roles === undefined || (role !== null && item.roles.includes(role)),
  );

  return (
    <div className="flex h-full flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)] text-neutral-100">
      <div className="flex h-[4.5rem] shrink-0 items-center justify-between border-b border-[var(--sidebar-border)] px-4">
        <div
          className={`flex min-w-0 items-center gap-3 ${collapsed ? "justify-center" : ""}`}
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-purple-400/40 bg-purple-600 text-xs font-bold tracking-wider text-white shadow-sm">
            FK
          </span>
          {!collapsed ? (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-wide text-white">
                FK SOLUTIONS
              </p>
              <p className="truncate text-[10px] font-medium uppercase tracking-[0.16em] text-neutral-400">
                AI Manufacturing Platform
              </p>
            </div>
          ) : null}
        </div>
        {mobile ? (
          <button
            aria-label="Close navigation"
            className="rounded-md p-2 text-neutral-300 hover:bg-[var(--sidebar-secondary)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400"
            onClick={onClose}
            ref={closeButtonRef}
            type="button"
          >
            <Icon name="close" />
          </button>
        ) : null}
      </div>

      <nav
        aria-label="Primary navigation"
        className="min-h-0 flex-1 overflow-y-auto px-3 py-5"
      >
        <ul className="space-y-1">
          {visibleNavigationItems.map((item) => (
            <li key={item.path}>
              <NavLink
                className={({ isActive }) =>
                  [
                    "group relative flex min-h-11 items-center rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400",
                    collapsed ? "justify-center" : "gap-3",
                    isActive
                      ? "bg-purple-700 text-white before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-purple-300"
                      : "text-neutral-300 hover:bg-[var(--sidebar-secondary)] hover:text-white",
                  ].join(" ")
                }
                end={item.path === "/"}
                onClick={onNavigate}
                title={collapsed ? item.label : undefined}
                to={item.path}
              >
                <Icon className="h-[1.125rem] w-[1.125rem] shrink-0" name={item.icon} />
                {!collapsed ? (
                  <span>{item.label}</span>
                ) : (
                  <span className="sr-only">{item.label}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {!mobile ? (
        <div className="border-t border-[var(--sidebar-border)] bg-[var(--sidebar)] p-3">
          <button
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={`flex w-full items-center rounded-md p-2 text-sm text-neutral-300 hover:bg-[var(--sidebar-secondary)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400 ${collapsed ? "justify-center" : "gap-3"}`}
            onClick={onToggleCollapsed}
            type="button"
          >
            <Icon
              className={`h-5 w-5 transition-transform ${collapsed ? "rotate-180" : ""}`}
              name="chevron-left"
            />
            {!collapsed ? <span>Collapse sidebar</span> : null}
          </button>
        </div>
      ) : null}
    </div>
  );
}
