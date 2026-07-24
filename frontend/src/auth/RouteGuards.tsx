import type { ReactElement } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useProductExperience } from "../product/productExperience";
import { useAuth } from "./useAuth";

export function AuthLoadingScreen(): ReactElement {
  return (
    <main
      aria-busy="true"
      className="flex min-h-screen items-center justify-center bg-stone-50 px-6"
    >
      <div className="text-center">
        <span
          aria-hidden="true"
          className="mx-auto block h-8 w-8 animate-spin rounded-full border-2 border-neutral-300 border-t-purple-700"
        />
        <p className="mt-4 text-sm font-medium text-neutral-600">
          Restoring your session…
        </p>
      </div>
    </main>
  );
}

export function ProtectedRoute(): ReactElement {
  const auth = useAuth();
  const location = useLocation();

  if (auth.status === "loading") {
    return <AuthLoadingScreen />;
  }
  if (!auth.isAuthenticated) {
    return (
      <Navigate
        replace
        state={{ from: `${location.pathname}${location.search}` }}
        to="/login"
      />
    );
  }
  return <Outlet />;
}

export function PublicOnlyRoute(): ReactElement {
  const auth = useAuth();
  const location = useLocation();
  const requestedDestination = (location.state as { readonly from?: unknown } | null)
    ?.from;
  const destination =
    typeof requestedDestination === "string" &&
    requestedDestination.startsWith("/") &&
    !requestedDestination.startsWith("//")
      ? requestedDestination
      : "/";

  if (auth.status === "loading") {
    return <AuthLoadingScreen />;
  }
  return auth.isAuthenticated ? <Navigate replace to={destination} /> : <Outlet />;
}

export function RoleRoute({
  roles,
}: {
  readonly roles: readonly ("admin" | "engineer" | "operator")[];
}): ReactElement {
  const auth = useAuth();
  if (auth.status === "loading") {
    return <AuthLoadingScreen />;
  }
  return auth.role !== null && roles.includes(auth.role) ? (
    <Outlet />
  ) : (
    <Navigate replace to="/" />
  );
}

export function OperationsFeatureRoute(): ReactElement {
  const { features, featuresLoading } = useProductExperience();
  if (featuresLoading) return <AuthLoadingScreen />;
  if (!features.operations_workflow_enabled) {
    return (
      <main className="rounded-lg border border-border bg-card p-8 shadow-panel">
        <h2 className="text-xl font-semibold text-foreground">
          Operations workflow is unavailable
        </h2>
        <p className="mt-2 text-sm text-secondary-foreground">
          This optional company workflow is disabled in the current environment.
        </p>
      </main>
    );
  }
  return <Outlet />;
}

export function DemoFeatureRoute(): ReactElement {
  const { features, featuresLoading } = useProductExperience();
  if (featuresLoading) return <AuthLoadingScreen />;
  if (!features.demo_tools_enabled) {
    return (
      <main className="rounded-lg border border-border bg-card p-8 shadow-panel">
        <h2 className="text-xl font-semibold text-foreground">
          Demo tools are unavailable
        </h2>
        <p className="mt-2 text-sm text-secondary-foreground">
          The controlled simulator and factory presentation tools are disabled in this
          environment.
        </p>
      </main>
    );
  }
  return <Outlet />;
}

export function ExpertModeRoute(): ReactElement {
  const { role } = useAuth();
  const { canSwitchMode, mode, setMode } = useProductExperience();
  if (role === "operator") return <Navigate replace to="/" />;
  if (mode === "expert") return <Outlet />;
  return (
    <main className="rounded-lg border border-border bg-card p-8 shadow-panel">
      <p className="text-xs font-semibold uppercase tracking-wide text-eyebrow">
        Expert mode
      </p>
      <h2 className="mt-2 text-xl font-semibold text-foreground">
        This technical area is hidden in Simple Mode
      </h2>
      <p className="mt-2 max-w-xl text-sm text-secondary-foreground">
        Switch to Expert Mode to use data, training, model, prediction, and governance
        tools. Changing presentation does not change your permissions.
      </p>
      {canSwitchMode ? (
        <button
          className="mt-5 rounded-md bg-purple-700 px-4 py-2 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() => setMode("expert")}
          type="button"
        >
          Switch to Expert Mode
        </button>
      ) : null}
    </main>
  );
}
