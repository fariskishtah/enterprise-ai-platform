import type { ReactElement } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

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
          className="mx-auto block h-8 w-8 animate-spin rounded-full border-2 border-neutral-300 border-t-teal-700"
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

  if (auth.status === "loading") {
    return <AuthLoadingScreen />;
  }
  return auth.isAuthenticated ? <Navigate replace to="/" /> : <Outlet />;
}
