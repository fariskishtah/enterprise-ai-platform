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
import { SensorDataPage } from "../pages/dataOperations/SensorDataPage";
import { SensorReadingsPage } from "../pages/dataOperations/SensorReadingsPage";
import { UploadJobDetailPage } from "../pages/dataOperations/UploadJobDetailPage";
import { UploadJobsPage } from "../pages/dataOperations/UploadJobsPage";
import { ModelDetailPage } from "../pages/aiLifecycle/ModelDetailPage";
import { ModelsPage } from "../pages/aiLifecycle/ModelsPage";
import { ModelVersionPage } from "../pages/aiLifecycle/ModelVersionPage";
import { TrainingJobDetailPage } from "../pages/aiLifecycle/TrainingJobDetailPage";
import { TrainingJobsPage } from "../pages/aiLifecycle/TrainingJobsPage";
import { AlertDetailPage } from "../pages/intelligence/AlertDetailPage";
import { AlertsPage } from "../pages/intelligence/AlertsPage";
import { EvaluationDetailPage } from "../pages/intelligence/EvaluationDetailPage";
import { ModelMonitoringPage } from "../pages/intelligence/ModelMonitoringPage";
import { MonitoringPage } from "../pages/intelligence/MonitoringPage";
import { PredictionEventDetailPage } from "../pages/intelligence/PredictionEventDetailPage";
import { PredictionHistoryPage } from "../pages/intelligence/PredictionHistoryPage";
import { PredictionsPage } from "../pages/intelligence/PredictionsPage";
import { RetrainingPage } from "../pages/intelligence/RetrainingPage";
import { RetrainingRequestPage } from "../pages/intelligence/RetrainingRequestPage";

const placeholderRoutes = [
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
          {
            element: <SensorReadingsPage />,
            path: "factories/:factoryId/machines/:machineId/sensors/:sensorId/readings",
          },
          { element: <SensorDataPage />, path: "sensor-data" },
          { element: <UploadJobsPage />, path: "sensor-data/uploads" },
          {
            element: <UploadJobDetailPage />,
            path: "sensor-data/uploads/:uploadJobId",
          },
          { element: <TrainingJobsPage />, path: "training" },
          { element: <TrainingJobDetailPage />, path: "training/:trainingJobId" },
          { element: <ModelsPage />, path: "models" },
          { element: <ModelDetailPage />, path: "models/:registeredModelName" },
          {
            element: <ModelVersionPage />,
            path: "models/:registeredModelName/versions/:versionOrAlias",
          },
          { element: <PredictionsPage />, path: "predictions" },
          { element: <PredictionHistoryPage />, path: "predictions/history" },
          {
            element: <PredictionEventDetailPage />,
            path: "predictions/history/:id",
          },
          { element: <MonitoringPage />, path: "monitoring" },
          {
            element: <EvaluationDetailPage />,
            path: "monitoring/evaluations/:id",
          },
          {
            element: <ModelMonitoringPage />,
            path: "monitoring/models/:registeredModelName/versions/:versionOrAlias",
          },
          { element: <AlertsPage />, path: "monitoring/alerts" },
          { element: <AlertDetailPage />, path: "monitoring/alerts/:id" },
          { element: <RetrainingPage />, path: "retraining" },
          {
            element: <RetrainingRequestPage />,
            path: "retraining/requests/:id",
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
