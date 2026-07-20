import type { RefObject, ReactElement } from "react";
import { NavLink } from "react-router-dom";

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
  return (
    <div className="flex h-full flex-col border-r border-neutral-200 bg-neutral-950 text-neutral-100">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-neutral-800 px-4">
        <div
          className={`flex min-w-0 items-center gap-3 ${collapsed ? "justify-center" : ""}`}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-teal-600 text-sm font-bold text-white">
            FM
          </span>
          {!collapsed ? (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">FactoryMind</p>
              <p className="truncate text-xs text-neutral-400">AI Manufacturing</p>
            </div>
          ) : null}
        </div>
        {mobile ? (
          <button
            aria-label="Close navigation"
            className="rounded-md p-2 text-neutral-300 hover:bg-neutral-800 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-400"
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
        className="min-h-0 flex-1 overflow-y-auto px-3 py-4"
      >
        <ul className="space-y-1">
          {navigationItems.map((item) => (
            <li key={item.path}>
              <NavLink
                className={({ isActive }) =>
                  [
                    "group flex min-h-10 items-center rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-400",
                    collapsed ? "justify-center" : "gap-3",
                    isActive
                      ? "bg-teal-700 text-white"
                      : "text-neutral-300 hover:bg-neutral-800 hover:text-white",
                  ].join(" ")
                }
                end={item.path === "/"}
                onClick={onNavigate}
                title={collapsed ? item.label : undefined}
                to={item.path}
              >
                <Icon className="h-5 w-5 shrink-0" name={item.icon} />
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
        <div className="border-t border-neutral-800 p-3">
          <button
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={`flex w-full items-center rounded-md p-2 text-sm text-neutral-400 hover:bg-neutral-800 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-400 ${collapsed ? "justify-center" : "gap-3"}`}
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
