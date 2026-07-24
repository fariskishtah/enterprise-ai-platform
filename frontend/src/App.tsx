import { Suspense, type ReactElement } from "react";
import { RouterProvider } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { ProductExperienceProvider } from "./product/ProductExperienceContext";
import { router } from "./routes/router";
import { ThemeProvider } from "./theme/ThemeContext";

export function App(): ReactElement {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ProductExperienceProvider>
          <Suspense
            fallback={
              <div
                className="flex min-h-screen items-center justify-center bg-[var(--app-bg)] text-sm text-[var(--text-secondary)]"
                role="status"
              >
                Loading workspace…
              </div>
            }
          >
            <RouterProvider router={router} />
          </Suspense>
        </ProductExperienceProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
