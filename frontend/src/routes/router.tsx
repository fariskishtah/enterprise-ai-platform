import { createBrowserRouter } from "react-router-dom";

import { ProtectedRoute, PublicOnlyRoute } from "../auth/RouteGuards";
import { AppShell } from "../components/AppShell";
import { Dashboard } from "../pages/Dashboard";
import { LoginPage } from "../pages/LoginPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";
import { NotFoundPage, RouteErrorPage } from "../pages/RouteErrorPages";
import { FactoriesPage } from "../pages/hierarchy/FactoriesPage";
import { FactoryDetailPage } from "../pages/hierarchy/FactoryDetailPage";
import { MachineDetailPage } from "../pages/hierarchy/MachineDetailPage";
import { SensorDetailPage } from "../pages/hierarchy/SensorDetailPage";

const placeholderRoutes = [
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
    children: [{ element: <LoginPage />, path: "login" }],
    element: <PublicOnlyRoute />,
    errorElement: <RouteErrorPage />,
    path: "/",
  },
  {
    children: [
      {
        children: [
          { element: <Dashboard />, index: true },
          { element: <FactoriesPage />, path: "factories" },
          { element: <FactoryDetailPage />, path: "factories/:factoryId" },
          {
            element: <MachineDetailPage />,
            path: "factories/:factoryId/machines/:machineId",
          },
          {
            element: <SensorDetailPage />,
            path: "factories/:factoryId/machines/:machineId/sensors/:sensorId",
          },
          ...placeholderRoutes.map(([path, title, description]) => ({
            element: <PlaceholderPage description={description} title={title} />,
            path,
          })),
          { element: <NotFoundPage />, path: "*" },
        ],
        element: <AppShell />,
      },
    ],
    element: <ProtectedRoute />,
    errorElement: <RouteErrorPage />,
    path: "/",
  },
]);
