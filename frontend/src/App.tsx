import type { ReactElement } from "react";
import { RouterProvider } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { router } from "./routes/router";
import { ThemeProvider } from "./theme/ThemeContext";

export function App(): ReactElement {
  return (
    <ThemeProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ThemeProvider>
  );
}
