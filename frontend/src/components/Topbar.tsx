import { useEffect, useRef, useState, type RefObject, type ReactElement } from "react";
import { Link, useLocation } from "react-router-dom";

import { isRequestCancelled } from "../api/client";
import { searchOperations, type OperationalSearchResult } from "../api/operations";
import { useAuth } from "../auth/useAuth";
import { useProductExperience } from "../product/productExperience";
import {
  readFavorites,
  readRecentResources,
  removeResourceShortcut,
  type ResourceShortcut,
} from "../product/resourcePreferences";
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
  const { canSwitchMode, features, mode, setMode } = useProductExperience();
  const { preference, setPreference } = useTheme();
  const location = useLocation();
  const initials = user?.email.slice(0, 2).toUpperCase() ?? "US";
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const [results, setResults] = useState<readonly OperationalSearchResult[]>([]);
  const [shortcuts, setShortcuts] = useState<{
    readonly favorites: readonly ResourceShortcut[];
    readonly recent: readonly ResourceShortcut[];
  }>({ favorites: [], recent: [] });

  useEffect(() => {
    if (user === null) return;
    const refresh = (): void =>
      setShortcuts({
        favorites: readFavorites(user.id),
        recent: readRecentResources(user.id),
      });
    refresh();
    window.addEventListener("fk-resource-shortcuts", refresh);
    return () => window.removeEventListener("fk-resource-shortcuts", refresh);
  }, [user]);

  useEffect(() => {
    if (!features.operations_workflow_enabled || query.trim().length < 2) {
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void searchOperations(query, controller.signal)
        .then((value) => setResults(value.items))
        .catch((error: unknown) => {
          if (!isRequestCancelled(error, controller.signal)) setResults([]);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [features.operations_workflow_enabled, query]);

  useEffect(() => {
    if (!accountMenuOpen) return;
    const closeOnOutsideClick = (event: PointerEvent): void => {
      if (
        event.target instanceof Node &&
        !accountMenuRef.current?.contains(event.target)
      ) {
        setAccountMenuOpen(false);
      }
    };
    const handleKeyboard = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setAccountMenuOpen(false);
        accountButtonRef.current?.focus();
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const items = Array.from(
        accountMenuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ??
          [],
      );
      if (items.length === 0) return;
      event.preventDefault();
      const current = items.indexOf(document.activeElement as HTMLElement);
      const next =
        event.key === "ArrowDown"
          ? (current + 1 + items.length) % items.length
          : (current - 1 + items.length) % items.length;
      items[next]?.focus();
    };
    window.addEventListener("pointerdown", closeOnOutsideClick);
    window.addEventListener("keydown", handleKeyboard);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutsideClick);
      window.removeEventListener("keydown", handleKeyboard);
    };
  }, [accountMenuOpen]);

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
        {features.operations_workflow_enabled ? (
          <div className="relative hidden w-[min(30vw,22rem)] lg:block">
            <label className="sr-only" htmlFor="operational-search">
              Search factories, machines, sensors, alerts, and actions
            </label>
            <input
              autoComplete="off"
              className="h-10 w-full rounded-md border border-border-strong bg-input px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              id="operational-search"
              onBlur={() => window.setTimeout(() => setSearchFocused(false), 120)}
              onChange={(event) => {
                setQuery(event.target.value);
                if (event.target.value.trim().length < 2) setResults([]);
              }}
              onFocus={() => setSearchFocused(true)}
              placeholder="Search operations"
              type="search"
              value={query}
            />
            {searchFocused &&
            (query.trim().length >= 2 ||
              shortcuts.favorites.length > 0 ||
              shortcuts.recent.length > 0) ? (
              <div className="absolute right-0 top-12 z-50 max-h-96 w-full overflow-y-auto rounded-lg border border-border bg-card p-2 shadow-lg">
                <SearchResults
                  favorites={shortcuts.favorites}
                  onNavigate={() => {
                    setQuery("");
                    setSearchFocused(false);
                  }}
                  onRemoveShortcut={(item) => {
                    if (user !== null) removeResourceShortcut(user.id, item);
                  }}
                  query={query}
                  recent={shortcuts.recent}
                  results={results}
                />
              </div>
            ) : null}
          </div>
        ) : null}
        {features.operations_workflow_enabled ? (
          <button
            aria-label="Open operational search"
            className="flex h-10 w-10 items-center justify-center rounded-md border border-border-strong bg-card text-secondary-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700 lg:hidden"
            onClick={() => setMobileSearchOpen(true)}
            type="button"
          >
            <Icon name="search" />
          </button>
        ) : null}
        {canSwitchMode ? (
          <label className="hidden items-center gap-2 text-xs font-semibold text-secondary-foreground md:flex">
            Experience
            <select
              aria-label="Product experience"
              className="h-10 rounded-md border border-border-strong bg-elevated px-2 text-sm font-medium text-secondary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onChange={(event) =>
                setMode(event.target.value === "simple" ? "simple" : "expert")
              }
              value={mode}
            >
              <option value="simple">Simple</option>
              <option value="expert">Expert</option>
            </select>
          </label>
        ) : null}
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
        <div className="relative" ref={accountMenuRef}>
          <button
            aria-expanded={accountMenuOpen}
            aria-haspopup="menu"
            aria-label={`Open account menu for ${user?.email ?? "current user"}`}
            className="flex h-10 items-center justify-center gap-2 rounded-md border border-border-strong bg-card px-2.5 text-xs font-bold text-secondary-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700"
            onClick={() => setAccountMenuOpen((value) => !value)}
            ref={accountButtonRef}
            type="button"
          >
            <span
              aria-hidden="true"
              className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--sidebar)] text-[10px] text-inverse"
            >
              {initials}
            </span>
            <span className="hidden min-w-0 text-left sm:block">
              <span className="block max-w-40 truncate text-sm font-medium">
                {user?.full_name ?? user?.email}
              </span>
              <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {role}
              </span>
            </span>
          </button>
          {accountMenuOpen ? (
            <div
              aria-label="Account options"
              className="absolute right-0 top-12 z-50 w-56 rounded-lg border border-border bg-card p-2 shadow-lg"
              role="menu"
            >
              <Link
                className="block rounded-md px-3 py-2 text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setAccountMenuOpen(false)}
                role="menuitem"
                to="/profile"
              >
                My Profile
              </Link>
              <Link
                className="block rounded-md px-3 py-2 text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setAccountMenuOpen(false)}
                role="menuitem"
                state={{ from: `${location.pathname}${location.search}` }}
                to="/support"
              >
                Contact Support
              </Link>
              <div className="my-1 border-t border-border" />
              <button
                className="block w-full rounded-md px-3 py-2 text-left text-sm font-medium text-danger-700 hover:bg-danger-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  setAccountMenuOpen(false);
                  void logout();
                }}
                role="menuitem"
                type="button"
              >
                Log Out
              </button>
            </div>
          ) : null}
        </div>
      </div>
      {mobileSearchOpen ? (
        <div
          aria-labelledby="mobile-search-heading"
          aria-modal="true"
          className="fixed inset-0 z-50 bg-neutral-950/60 p-4 lg:hidden"
          role="dialog"
        >
          <div className="mx-auto max-h-full max-w-xl overflow-y-auto rounded-lg border border-border bg-card p-4 shadow-lg">
            <div className="flex items-center justify-between gap-4">
              <h2
                className="text-lg font-semibold text-foreground"
                id="mobile-search-heading"
              >
                Search operations
              </h2>
              <button
                aria-label="Close operational search"
                className="rounded-md p-2 text-secondary-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setMobileSearchOpen(false)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </div>
            <label className="sr-only" htmlFor="mobile-operational-search">
              Search factories, machines, sensors, alerts, and actions
            </label>
            <input
              autoComplete="off"
              autoFocus
              className="mt-4 h-11 w-full rounded-md border border-border-strong bg-input px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              id="mobile-operational-search"
              onChange={(event) => {
                setQuery(event.target.value);
                if (event.target.value.trim().length < 2) setResults([]);
              }}
              placeholder="Search factories, machines, alerts, and actions"
              type="search"
              value={query}
            />
            <div className="mt-3">
              <SearchResults
                favorites={shortcuts.favorites}
                onNavigate={() => {
                  setQuery("");
                  setMobileSearchOpen(false);
                }}
                onRemoveShortcut={(item) => {
                  if (user !== null) removeResourceShortcut(user.id, item);
                }}
                query={query}
                recent={shortcuts.recent}
                results={results}
              />
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}

function SearchResults({
  favorites,
  onNavigate,
  onRemoveShortcut,
  query,
  recent,
  results,
}: {
  readonly favorites: readonly ResourceShortcut[];
  readonly onNavigate: () => void;
  readonly onRemoveShortcut: (item: ResourceShortcut) => void;
  readonly query: string;
  readonly recent: readonly ResourceShortcut[];
  readonly results: readonly OperationalSearchResult[];
}): ReactElement {
  if (query.trim().length >= 2) {
    return results.length > 0 ? (
      <ul aria-label="Operational search results">
        {results.map((item) => (
          <li key={`${item.resource_type}-${item.id}`}>
            <Link
              className="block rounded-md px-3 py-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={onNavigate}
              to={item.path}
            >
              <span className="block text-sm font-semibold text-foreground">
                {item.label}
              </span>
              <span className="block text-xs capitalize text-muted-foreground">
                {item.resource_type.replaceAll("_", " ")}
                {item.description ? ` · ${item.description}` : ""}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    ) : (
      <p className="px-3 py-4 text-sm text-secondary-foreground">
        No authorized operational resources match this prefix.
      </p>
    );
  }
  const items = [...favorites, ...recent].filter(
    (item, index, all) =>
      all.findIndex(
        (candidate) => candidate.type === item.type && candidate.id === item.id,
      ) === index,
  );
  return (
    <div>
      <p className="px-3 py-2 text-xs font-semibold uppercase text-muted-foreground">
        Favorites and recent
      </p>
      <ul>
        {items.slice(0, 8).map((item) => (
          <li
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center"
            key={`${item.type}-${item.id}`}
          >
            <Link
              className="block rounded-md px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={onNavigate}
              to={item.path}
            >
              {item.label}
              <span className="ml-2 text-xs font-normal capitalize text-muted-foreground">
                {item.type}
              </span>
            </Link>
            <button
              aria-label={`Remove ${item.label} stored shortcut`}
              className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onRemoveShortcut(item)}
              title="Remove stored shortcut"
              type="button"
            >
              <Icon className="h-4 w-4" name="close" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
