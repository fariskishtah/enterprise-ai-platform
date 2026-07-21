import { useEffect, useRef, useState, type ReactElement } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { getNavigationItem } from "../navigation";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell(): ReactElement {
  const location = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const currentPage = getNavigationItem(location.pathname);

  useEffect(() => {
    if (!isMobileOpen) {
      return;
    }
    closeButtonRef.current?.focus();

    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setIsMobileOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isMobileOpen]);

  const closeMobileNavigation = (): void => {
    setIsMobileOpen(false);
    menuButtonRef.current?.focus();
  };

  return (
    <div className="flex min-h-screen w-full overflow-x-hidden bg-canvas text-foreground">
      <aside
        className={`hidden shrink-0 transition-[width] duration-200 lg:block ${isCollapsed ? "w-20" : "w-64"}`}
      >
        <div
          className="fixed inset-y-0 left-0"
          style={{ width: isCollapsed ? 80 : 256 }}
        >
          <Sidebar
            collapsed={isCollapsed}
            onToggleCollapsed={() => setIsCollapsed((value) => !value)}
          />
        </div>
      </aside>

      {isMobileOpen ? (
        <div
          aria-label="Mobile navigation"
          aria-modal="true"
          className="fixed inset-0 z-40 lg:hidden"
          role="dialog"
        >
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-neutral-950/60"
            onClick={closeMobileNavigation}
            type="button"
          />
          <aside className="relative h-full w-[min(20rem,85vw)] shadow-lg">
            <Sidebar
              closeButtonRef={closeButtonRef}
              mobile
              onClose={closeMobileNavigation}
              onNavigate={() => setIsMobileOpen(false)}
            />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          menuButtonRef={menuButtonRef}
          onOpenNavigation={() => setIsMobileOpen(true)}
          title={currentPage.label}
        />
        <main className="min-w-0 flex-1" id="main-content">
          <div className="mx-auto w-full max-w-screen-2xl px-4 py-6 sm:px-6 sm:py-8 lg:px-10 lg:py-9">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
