import { lazy } from "react";
import { createBrowserRouter } from "react-router-dom";

import {
  DemoFeatureRoute,
  ExpertModeRoute,
  OperationsFeatureRoute,
  ProtectedRoute,
  PublicOnlyRoute,
  RoleRoute,
} from "../auth/RouteGuards";
import { AppShell } from "../components/AppShell";
import { NotFoundPage, RouteErrorPage } from "../pages/RouteErrorPages";

const HomePage = lazy(() =>
  import("../pages/operations/HomePage").then(({ HomePage }) => ({
    default: HomePage,
  })),
);
const LoginPage = lazy(() =>
  import("../pages/LoginPage").then(({ LoginPage }) => ({ default: LoginPage })),
);
const RegisterPage = lazy(() =>
  import("../pages/RegisterPage").then(({ RegisterPage }) => ({
    default: RegisterPage,
  })),
);
const AuditLogsPage = lazy(() =>
  import("../pages/AuditLogsPage").then(({ AuditLogsPage }) => ({
    default: AuditLogsPage,
  })),
);
const SettingsPage = lazy(() =>
  import("../pages/SettingsPage").then(({ SettingsPage }) => ({
    default: SettingsPage,
  })),
);
const MyProfilePage = lazy(() =>
  import("../pages/account/MyProfilePage").then(({ MyProfilePage }) => ({
    default: MyProfilePage,
  })),
);
const ContactSupportPage = lazy(() =>
  import("../pages/account/ContactSupportPage").then(({ ContactSupportPage }) => ({
    default: ContactSupportPage,
  })),
);
const UsersPage = lazy(() =>
  import("../pages/UsersPage").then(({ UsersPage }) => ({ default: UsersPage })),
);
const MachineRiskPage = lazy(() =>
  import("../pages/pilot/MachineRiskPage").then(({ MachineRiskPage }) => ({
    default: MachineRiskPage,
  })),
);
const FactoriesPage = lazy(() =>
  import("../pages/hierarchy/FactoriesPage").then(({ FactoriesPage }) => ({
    default: FactoriesPage,
  })),
);
const FactoryDetailPage = lazy(() =>
  import("../pages/hierarchy/FactoryDetailPage").then(({ FactoryDetailPage }) => ({
    default: FactoryDetailPage,
  })),
);
const MachineDetailPage = lazy(() =>
  import("../pages/hierarchy/MachineDetailPage").then(({ MachineDetailPage }) => ({
    default: MachineDetailPage,
  })),
);
const SensorDetailPage = lazy(() =>
  import("../pages/hierarchy/SensorDetailPage").then(({ SensorDetailPage }) => ({
    default: SensorDetailPage,
  })),
);
const SensorDataPage = lazy(() =>
  import("../pages/dataOperations/SensorDataPage").then(({ SensorDataPage }) => ({
    default: SensorDataPage,
  })),
);
const SensorReadingsPage = lazy(() =>
  import("../pages/dataOperations/SensorReadingsPage").then(
    ({ SensorReadingsPage }) => ({ default: SensorReadingsPage }),
  ),
);
const UploadJobDetailPage = lazy(() =>
  import("../pages/dataOperations/UploadJobDetailPage").then(
    ({ UploadJobDetailPage }) => ({ default: UploadJobDetailPage }),
  ),
);
const UploadJobsPage = lazy(() =>
  import("../pages/dataOperations/UploadJobsPage").then(({ UploadJobsPage }) => ({
    default: UploadJobsPage,
  })),
);
const ModelDetailPage = lazy(() =>
  import("../pages/aiLifecycle/ModelDetailPage").then(({ ModelDetailPage }) => ({
    default: ModelDetailPage,
  })),
);
const ModelsPage = lazy(() =>
  import("../pages/aiLifecycle/ModelsPage").then(({ ModelsPage }) => ({
    default: ModelsPage,
  })),
);
const ModelVersionPage = lazy(() =>
  import("../pages/aiLifecycle/ModelVersionPage").then(({ ModelVersionPage }) => ({
    default: ModelVersionPage,
  })),
);
const TrainingJobDetailPage = lazy(() =>
  import("../pages/aiLifecycle/TrainingJobDetailPage").then(
    ({ TrainingJobDetailPage }) => ({ default: TrainingJobDetailPage }),
  ),
);
const TrainingJobsPage = lazy(() =>
  import("../pages/aiLifecycle/TrainingJobsPage").then(({ TrainingJobsPage }) => ({
    default: TrainingJobsPage,
  })),
);
const EvaluationsPage = lazy(() =>
  import("../pages/aiLifecycle/EvaluationsPage").then(({ EvaluationsPage }) => ({
    default: EvaluationsPage,
  })),
);
const TrainingEvaluationPage = lazy(() =>
  import("../pages/aiLifecycle/TrainingEvaluationPage").then(
    ({ TrainingEvaluationPage }) => ({ default: TrainingEvaluationPage }),
  ),
);
const AlertDetailPage = lazy(() =>
  import("../pages/operations/AlertsRouterPage").then(({ AlertDetailRouterPage }) => ({
    default: AlertDetailRouterPage,
  })),
);
const AlertsPage = lazy(() =>
  import("../pages/operations/AlertsRouterPage").then(({ AlertsRouterPage }) => ({
    default: AlertsRouterPage,
  })),
);
const MachinesPage = lazy(() =>
  import("../pages/operations/MachinesPage").then(({ MachinesPage }) => ({
    default: MachinesPage,
  })),
);
const RequiredActionsPage = lazy(() =>
  import("../pages/operations/RequiredActionsPage").then(({ RequiredActionsPage }) => ({
    default: RequiredActionsPage,
  })),
);
const ActionDetailPage = lazy(() =>
  import("../pages/operations/ActionDetailPage").then(({ ActionDetailPage }) => ({
    default: ActionDetailPage,
  })),
);
const ActivityPage = lazy(() =>
  import("../pages/operations/ActivityPage").then(({ ActivityPage }) => ({
    default: ActivityPage,
  })),
);
const MachineTimelinePage = lazy(() =>
  import("../pages/operations/MachineTimelinePage").then(({ MachineTimelinePage }) => ({
    default: MachineTimelinePage,
  })),
);
const ShiftsPage = lazy(() =>
  import("../pages/operations/ShiftsPage").then(({ ShiftsPage }) => ({
    default: ShiftsPage,
  })),
);
const ShiftDetailPage = lazy(() =>
  import("../pages/operations/ShiftDetailPage").then(({ ShiftDetailPage }) => ({
    default: ShiftDetailPage,
  })),
);
const EvaluationDetailPage = lazy(() =>
  import("../pages/intelligence/EvaluationDetailPage").then(
    ({ EvaluationDetailPage }) => ({ default: EvaluationDetailPage }),
  ),
);
const ModelMonitoringPage = lazy(() =>
  import("../pages/intelligence/ModelMonitoringPage").then(
    ({ ModelMonitoringPage }) => ({ default: ModelMonitoringPage }),
  ),
);
const MonitoringPage = lazy(() =>
  import("../pages/intelligence/MonitoringPage").then(({ MonitoringPage }) => ({
    default: MonitoringPage,
  })),
);
const PredictionEventDetailPage = lazy(() =>
  import("../pages/intelligence/PredictionEventDetailPage").then(
    ({ PredictionEventDetailPage }) => ({
      default: PredictionEventDetailPage,
    }),
  ),
);
const PredictionHistoryPage = lazy(() =>
  import("../pages/intelligence/PredictionHistoryPage").then(
    ({ PredictionHistoryPage }) => ({ default: PredictionHistoryPage }),
  ),
);
const PredictionsPage = lazy(() =>
  import("../pages/intelligence/PredictionsPage").then(({ PredictionsPage }) => ({
    default: PredictionsPage,
  })),
);
const RetrainingPage = lazy(() =>
  import("../pages/intelligence/RetrainingPage").then(({ RetrainingPage }) => ({
    default: RetrainingPage,
  })),
);
const RetrainingRequestPage = lazy(() =>
  import("../pages/intelligence/RetrainingRequestPage").then(
    ({ RetrainingRequestPage }) => ({ default: RetrainingRequestPage }),
  ),
);
const AutoMLStudiesPage = lazy(() =>
  import("../pages/automl/AutoMLStudiesPage").then(({ AutoMLStudiesPage }) => ({
    default: AutoMLStudiesPage,
  })),
);
const AutoMLCreatePage = lazy(() =>
  import("../pages/automl/AutoMLCreatePage").then(({ AutoMLCreatePage }) => ({
    default: AutoMLCreatePage,
  })),
);
const AutoMLStudyDetailPage = lazy(() =>
  import("../pages/automl/AutoMLStudyDetailPage").then(({ AutoMLStudyDetailPage }) => ({
    default: AutoMLStudyDetailPage,
  })),
);
const AutoMLTrialDetailPage = lazy(() =>
  import("../pages/automl/AutoMLTrialDetailPage").then(({ AutoMLTrialDetailPage }) => ({
    default: AutoMLTrialDetailPage,
  })),
);
const DatasetCreatePage = lazy(() =>
  import("../pages/datasets/DatasetCreatePage").then(({ DatasetCreatePage }) => ({
    default: DatasetCreatePage,
  })),
);
const DatasetDetailPage = lazy(() =>
  import("../pages/datasets/DatasetDetailPage").then(({ DatasetDetailPage }) => ({
    default: DatasetDetailPage,
  })),
);
const DatasetDocumentPage = lazy(() =>
  import("../pages/datasets/DatasetDocumentPage").then(({ DatasetDocumentPage }) => ({
    default: DatasetDocumentPage,
  })),
);
const DatasetsPage = lazy(() =>
  import("../pages/datasets/DatasetsPage").then(({ DatasetsPage }) => ({
    default: DatasetsPage,
  })),
);
const DatasetVersionPage = lazy(() =>
  import("../pages/datasets/DatasetVersionPage").then(({ DatasetVersionPage }) => ({
    default: DatasetVersionPage,
  })),
);
const KnowledgeBaseCreatePage = lazy(() =>
  import("../pages/knowledge/KnowledgeBaseCreatePage").then(
    ({ KnowledgeBaseCreatePage }) => ({ default: KnowledgeBaseCreatePage }),
  ),
);
const KnowledgeBaseDetailPage = lazy(() =>
  import("../pages/knowledge/KnowledgeBaseDetailPage").then(
    ({ KnowledgeBaseDetailPage }) => ({ default: KnowledgeBaseDetailPage }),
  ),
);
const KnowledgeBasesPage = lazy(() =>
  import("../pages/knowledge/KnowledgeBasesPage").then(({ KnowledgeBasesPage }) => ({
    default: KnowledgeBasesPage,
  })),
);
const ChatPage = lazy(() =>
  import("../pages/chat/ChatPage").then(({ ChatPage }) => ({
    default: ChatPage,
  })),
);
const ConversationPage = lazy(() =>
  import("../pages/chat/ConversationPage").then(({ ConversationPage }) => ({
    default: ConversationPage,
  })),
);
const DataOnboardingPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ DataOnboardingPage }) => ({
    default: DataOnboardingPage,
  })),
);
const DataQualityPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ DataQualityPage }) => ({
    default: DataQualityPage,
  })),
);
const GuidedAiPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ GuidedAiPage }) => ({
    default: GuidedAiPage,
  })),
);
const DemoControlPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ DemoControlPage }) => ({
    default: DemoControlPage,
  })),
);
const FactoryMapPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ FactoryMapPage }) => ({
    default: FactoryMapPage,
  })),
);
const TvModePage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ TvModePage }) => ({
    default: TvModePage,
  })),
);
const ExecutiveDashboardPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ ExecutiveDashboardPage }) => ({
    default: ExecutiveDashboardPage,
  })),
);
const ReportsPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ ReportsPage }) => ({
    default: ReportsPage,
  })),
);
const ReportDetailPage = lazy(() =>
  import("../pages/demo/DemoExperiencePages").then(({ ReportDetailPage }) => ({
    default: ReportDetailPage,
  })),
);

export const router = createBrowserRouter([
  {
    children: [
      { element: <LoginPage />, path: "login" },
      { element: <RegisterPage />, path: "register" },
    ],
    element: <PublicOnlyRoute />,
    errorElement: <RouteErrorPage />,
    path: "/",
  },
  {
    children: [
      {
        children: [
          { element: <HomePage />, index: true },
          { element: <FactoriesPage />, path: "factories" },
          {
            children: [
              {
                element: <FactoryMapPage />,
                path: "factories/:factoryId/map",
              },
              { element: <TvModePage />, path: "factories/:factoryId/tv" },
              {
                element: <RoleRoute roles={["admin", "engineer"]} />,
                children: [{ element: <DemoControlPage />, path: "demo/control" }],
              },
            ],
            element: <DemoFeatureRoute />,
          },
          {
            children: [
              { element: <MachinesPage />, path: "machines" },
              { element: <RequiredActionsPage />, path: "operations/actions" },
              {
                element: <ActionDetailPage />,
                path: "operations/actions/:actionId",
              },
              { element: <ActivityPage />, path: "activity" },
              { element: <ShiftsPage />, path: "operations/shifts" },
              {
                element: <ShiftDetailPage />,
                path: "operations/shifts/:shiftId",
              },
              {
                element: <MachineTimelinePage />,
                path: "factories/:factoryId/machines/:machineId/timeline",
              },
            ],
            element: <OperationsFeatureRoute />,
          },
          { element: <FactoryDetailPage />, path: "factories/:factoryId" },
          {
            element: <MachineDetailPage />,
            path: "factories/:factoryId/machines/:machineId",
          },
          {
            element: <MachineRiskPage />,
            path: "factories/:factoryId/machines/:machineId/risk",
          },
          {
            element: <SensorDetailPage />,
            path: "factories/:factoryId/machines/:machineId/sensors/:sensorId",
          },
          {
            element: <SensorReadingsPage />,
            path: "factories/:factoryId/machines/:machineId/sensors/:sensorId/readings",
          },
          {
            children: [
              { element: <SensorDataPage />, path: "sensor-data" },
              {
                element: <DataOnboardingPage />,
                path: "sensor-data/onboarding",
              },
              { element: <DataQualityPage />, path: "sensor-data/quality" },
              { element: <GuidedAiPage />, path: "guided-ai" },
              { element: <UploadJobsPage />, path: "sensor-data/uploads" },
              {
                element: <UploadJobDetailPage />,
                path: "sensor-data/uploads/:uploadJobId",
              },
              {
                children: [
                  { element: <DatasetsPage />, index: true },
                  { element: <DatasetCreatePage />, path: "new" },
                  { element: <DatasetDetailPage />, path: ":datasetId" },
                  {
                    element: <DatasetVersionPage />,
                    path: ":datasetId/versions/:versionId",
                  },
                  {
                    element: <DatasetDocumentPage />,
                    path: ":datasetId/versions/:versionId/documents/:documentId",
                  },
                ],
                element: <RoleRoute roles={["admin", "engineer"]} />,
                path: "datasets",
              },
              { element: <TrainingJobsPage />, path: "training" },
              {
                element: <TrainingJobDetailPage />,
                path: "training/:trainingJobId",
              },
              {
                children: [
                  { element: <AutoMLStudiesPage />, index: true },
                  { element: <AutoMLCreatePage />, path: "new" },
                  { element: <AutoMLStudyDetailPage />, path: ":studyId" },
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
              {
                element: <ModelDetailPage />,
                path: "models/:registeredModelName",
              },
              {
                element: <ModelVersionPage />,
                path: "models/:registeredModelName/versions/:versionOrAlias",
              },
              { element: <PredictionsPage />, path: "predictions" },
              {
                element: <PredictionHistoryPage />,
                path: "predictions/history",
              },
              {
                element: <PredictionEventDetailPage />,
                path: "predictions/history/:id",
              },
              {
                children: [
                  { element: <KnowledgeBasesPage />, index: true },
                  { element: <KnowledgeBaseCreatePage />, path: "new" },
                  {
                    element: <KnowledgeBaseDetailPage />,
                    path: ":knowledgeBaseId",
                  },
                ],
                element: <RoleRoute roles={["admin", "engineer"]} />,
                path: "knowledge",
              },
              {
                children: [
                  { element: <ChatPage />, index: true },
                  { element: <ConversationPage />, path: ":conversationId" },
                ],
                element: <RoleRoute roles={["admin", "engineer"]} />,
                path: "chat",
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
            ],
            element: <ExpertModeRoute />,
          },
          { element: <AlertsPage />, path: "monitoring/alerts" },
          { element: <AlertDetailPage />, path: "monitoring/alerts/:id" },
          {
            children: [
              { element: <RetrainingPage />, path: "retraining" },
              {
                element: <RetrainingRequestPage />,
                path: "retraining/requests/:id",
              },
              { element: <AuditLogsPage />, path: "audit-log" },
            ],
            element: <ExpertModeRoute />,
          },
          { element: <SettingsPage />, path: "settings" },
          { element: <MyProfilePage />, path: "profile" },
          { element: <ContactSupportPage />, path: "support" },
          {
            children: [
              {
                element: <ExecutiveDashboardPage />,
                path: "executive",
              },
              { element: <ReportsPage />, path: "reports" },
              { element: <ReportDetailPage />, path: "reports/:reportId" },
            ],
            element: <RoleRoute roles={["admin"]} />,
          },
          {
            children: [{ element: <UsersPage />, index: true }],
            element: <RoleRoute roles={["admin"]} />,
            path: "users",
          },
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
