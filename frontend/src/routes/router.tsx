import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { Dashboard } from "../pages/Dashboard";
import { PlaceholderPage } from "../pages/PlaceholderPage";
import { NotFoundPage, RouteErrorPage } from "../pages/RouteErrorPages";

const placeholderRoutes = [
  ["factories", "Factories", "Manufacturing sites and production hierarchy."],
  ["sensor-data", "Sensor Data", "Sensor readings and ingestion activity."],
  ["training-jobs", "Training Jobs", "Background model training execution."],
  ["models", "Models", "Registered models and immutable versions."],
  ["predictions", "Predictions", "Run and inspect registered-model predictions."],
  ["monitoring", "Monitoring", "Model health, data quality, and drift."],
  ["audit-log", "Audit Log", "Governance decisions and operational history."],
  ["users", "Users & Roles", "User access and role administration."],
  ["settings", "Settings", "Platform and workspace preferences."],
] as const;

export const router = createBrowserRouter([
  {
    children: [
      { element: <Dashboard />, index: true },
      ...placeholderRoutes.map(([path, title, description]) => ({
        element: <PlaceholderPage description={description} title={title} />,
        path,
      })),
      { element: <NotFoundPage />, path: "*" },
    ],
    element: <AppShell />,
    errorElement: <RouteErrorPage />,
    path: "/",
  },
]);
