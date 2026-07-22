import { createBrowserRouter } from "react-router-dom";

import { ProtectedRoute, PublicOnlyRoute, RoleRoute } from "../auth/RouteGuards";
import { AppShell } from "../components/AppShell";
import { Dashboard } from "../pages/Dashboard";
import { LoginPage } from "../pages/LoginPage";
import { AuditLogsPage } from "../pages/AuditLogsPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";
import { SettingsPage } from "../pages/SettingsPage";
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
import { EvaluationsPage } from "../pages/aiLifecycle/EvaluationsPage";
import { TrainingEvaluationPage } from "../pages/aiLifecycle/TrainingEvaluationPage";
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
import { AutoMLStudiesPage } from "../pages/automl/AutoMLStudiesPage";
import { AutoMLCreatePage } from "../pages/automl/AutoMLCreatePage";
import { AutoMLStudyDetailPage } from "../pages/automl/AutoMLStudyDetailPage";
import { AutoMLTrialDetailPage } from "../pages/automl/AutoMLTrialDetailPage";

const placeholderRoutes = [
  ["users", "Users & Roles", "User access and role administration."],
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
          {
            children: [
              { element: <AutoMLStudiesPage />, index: true },
              { element: <AutoMLCreatePage />, path: "new" },
              { element: <AutoMLStudyDetailPage />, path: "studies/:studyId" },
              {
                element: <AutoMLTrialDetailPage />,
                path: "studies/:studyId/trials/:trialId",
              },
            ],
            element: <RoleRoute roles={["admin", "engineer"]} />,
            path: "automl",
          },
          { element: <EvaluationsPage />, path: "evaluations" },
          {
            element: <TrainingEvaluationPage />,
            path: "evaluations/jobs/:trainingJobId",
          },
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
          { element: <AuditLogsPage />, path: "audit-log" },
          { element: <SettingsPage />, path: "settings" },
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
