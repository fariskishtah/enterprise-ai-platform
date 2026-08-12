import { useMemo, useState, type ReactElement, type RefObject } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import {
  getNavigationItem,
  getVisibleNavigationItems,
  getVisibleNavigationSections,
  type NavigationGroup,
  type NavigationItem,
} from "../navigation";
import { useProductExperience } from "../product/productExperience";
import { Icon } from "./Icon";
import { IconMotion } from "./IconMotion";

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
  const { features, mode } = useProductExperience();
  const location = useLocation();
  const demoToolsEnabled = features.demo_tools_enabled;
  const operationsWorkflowEnabled = features.operations_workflow_enabled;
  const visibleNavigationItems = useMemo(
    () =>
      getVisibleNavigationItems(role, mode, {
        demo_tools_enabled: demoToolsEnabled,
        operations_workflow_enabled: operationsWorkflowEnabled,
      }),
    [demoToolsEnabled, mode, operationsWorkflowEnabled, role],
  );
  const visibleSections = useMemo(
    () =>
      getVisibleNavigationSections(role, mode, {
        demo_tools_enabled: demoToolsEnabled,
        operations_workflow_enabled: operationsWorkflowEnabled,
      }),
    [demoToolsEnabled, mode, operationsWorkflowEnabled, role],
  );
  const activeGroup = getNavigationItem(location.pathname).group;
  const [groupPreferences, setGroupPreferences] = useState<
    Partial<Record<NavigationGroup, boolean>>
  >({});

  const isGroupExpanded = (group: NavigationGroup): boolean =>
    group === activeGroup ||
    (groupPreferences[group] ??
      (group !== "advanced-ai" || role === "engineer" || role === "analyst"));

  const toggleGroup = (group: NavigationGroup): void => {
    setGroupPreferences((current) => {
      const expanded =
        group === activeGroup ||
        (current[group] ??
          (group !== "advanced-ai" || role === "engineer" || role === "analyst"));
      return { ...current, [group]: !expanded };
    });
  };

  return (
    <div className="flex h-full flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)] text-[var(--sidebar-text-strong)]">
      <div className="flex h-[4.5rem] shrink-0 items-center justify-between border-b border-[var(--sidebar-border)] px-4">
        <div
          className={`flex min-w-0 items-center gap-3 ${collapsed ? "justify-center" : ""}`}
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-purple-300/40 bg-[var(--sidebar-brand)] text-xs font-bold tracking-wider text-white shadow-sm">
            FK
          </span>
          {!collapsed ? (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-wide text-white">
                FactoryMind
              </p>
              <p className="truncate text-[10px] font-medium uppercase tracking-[0.16em] text-neutral-400">
                Manufacturing workspace
              </p>
            </div>
          ) : null}
        </div>
        {mobile ? (
          <button
            aria-label="Close navigation"
            className="rounded-md p-2 text-[var(--sidebar-text)] hover:bg-[var(--sidebar-secondary)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400"
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
        {collapsed ? (
          <ul className="space-y-1">
            {visibleNavigationItems.map((item) => (
              <NavigationLink
                collapsed
                item={item}
                key={item.path}
                onNavigate={onNavigate}
              />
            ))}
          </ul>
        ) : (
          <div className="space-y-2">
            {visibleSections.map((section) => {
              const expanded = isGroupExpanded(section.id);
              const sectionId = `navigation-${section.id}`;
              return (
                <section key={section.id}>
                  <button
                    aria-controls={sectionId}
                    aria-expanded={expanded}
                    className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-neutral-400 hover:bg-[var(--sidebar-secondary)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400"
                    onClick={() => toggleGroup(section.id)}
                    title={section.description}
                    type="button"
                  >
                    <span>{section.label}</span>
                    <Icon
                      className={`h-4 w-4 transition-transform ${expanded ? "-rotate-90" : "rotate-180"}`}
                      name="chevron-left"
                    />
                  </button>
                  {expanded ? (
                    <ul className="mt-1 space-y-1" id={sectionId}>
                      {section.items.map((item) => (
                        <NavigationLink
                          item={item}
                          key={item.path}
                          onNavigate={onNavigate}
                        />
                      ))}
                    </ul>
                  ) : null}
                </section>
              );
            })}
          </div>
        )}
      </nav>

      {!mobile ? (
        <div className="border-t border-[var(--sidebar-border)] bg-[var(--sidebar)] p-3">
          <button
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={`flex w-full items-center rounded-md p-2 text-sm text-[var(--sidebar-text)] hover:bg-[var(--sidebar-secondary)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400 ${collapsed ? "justify-center" : "gap-3"}`}
            onClick={onToggleCollapsed}
            type="button"
          >
            <Icon
              className={`h-5 w-5 transition-transform ${collapsed ? "rotate-180" : ""}`}
              name="chevron-left"
            />
            {!collapsed ? <span>Collapse navigation</span> : null}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function NavigationLink({
  collapsed = false,
  item,
  onNavigate,
}: {
  readonly collapsed?: boolean;
  readonly item: NavigationItem;
  readonly onNavigate?: () => void;
}): ReactElement {
  return (
    <li>
      <NavLink
        className={({ isActive }) =>
          [
            "group relative flex min-h-11 items-center rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-400",
            collapsed ? "justify-center" : "gap-3",
            isActive
              ? "bg-[var(--sidebar-active)] text-white before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-purple-300"
              : "text-[var(--sidebar-text)] hover:bg-[var(--sidebar-secondary)] hover:text-white",
          ].join(" ")
        }
        end={item.path === "/" || item.path === "/settings"}
        onClick={onNavigate}
        title={collapsed ? `${item.label}: ${item.description}` : item.description}
        to={item.path}
      >
        {({ isActive }) => (
          <>
            <IconMotion active={isActive} motion={item.motion}>
              <Icon className="h-[1.125rem] w-[1.125rem]" name={item.icon} />
            </IconMotion>
            {!collapsed ? (
              <span>{item.label}</span>
            ) : (
              <span className="sr-only">{item.label}</span>
            )}
          </>
        )}
      </NavLink>
    </li>
  );
}
