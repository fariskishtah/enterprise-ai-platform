import { hasLegacyRoleAccess } from "./auth/permissions";
import type { UserRole } from "./auth/authApi";

export type NavigationRole = UserRole;
export type NavigationMode = "expert" | "simple";
export type NavigationFeature = "demo" | "operations";
export type NavigationMotion =
  | "bounce"
  | "chart-rise"
  | "flow"
  | "glow"
  | "lift"
  | "none"
  | "pop"
  | "progress"
  | "pulse"
  | "rotate"
  | "shake";

export type NavigationIcon =
  | "audit"
  | "automl"
  | "chat"
  | "dashboard"
  | "datasets"
  | "factories"
  | "knowledge"
  | "models"
  | "monitoring"
  | "predictions"
  | "retraining"
  | "sensor-data"
  | "settings"
  | "users"
  | "training-jobs";

export interface NavigationItem {
  readonly description: string;
  readonly feature?: NavigationFeature;
  readonly icon: NavigationIcon;
  readonly label: string;
  readonly motion: NavigationMotion;
  readonly modes?: readonly NavigationMode[];
  readonly path: string;
  readonly roles?: readonly NavigationRole[];
  readonly sidebar?: boolean;
}

export const navigationItems: readonly NavigationItem[] = [
  {
    description: "Operational overview and platform status.",
    icon: "dashboard",
    label: "Home",
    motion: "chart-rise",
    path: "/",
  },
  {
    description: "Manufacturing sites and production hierarchy.",
    icon: "factories",
    label: "Factory Overview",
    motion: "lift",
    path: "/factories",
  },
  {
    description: "Machines available in your authorized factories.",
    icon: "factories",
    label: "Machines",
    motion: "rotate",
    modes: ["simple"],
    path: "/machines",
  },
  {
    description: "Prioritized maintenance and operational work.",
    feature: "operations",
    icon: "audit",
    label: "Required Actions",
    motion: "pop",
    modes: ["simple"],
    path: "/operations/actions",
  },
  {
    description: "Open machine and monitoring conditions requiring attention.",
    feature: "operations",
    icon: "monitoring",
    label: "Alerts",
    motion: "shake",
    modes: ["simple"],
    path: "/monitoring/alerts",
  },
  {
    description: "Recent operational events across authorized factories.",
    feature: "operations",
    icon: "audit",
    label: "Activity",
    motion: "flow",
    modes: ["simple"],
    path: "/activity",
  },
  {
    description: "Active shifts, unresolved work, and handover history.",
    feature: "operations",
    icon: "audit",
    label: "Shift Handover",
    motion: "flow",
    modes: ["simple"],
    path: "/operations/shifts",
  },
  {
    description: "Sensor readings and ingestion activity.",
    icon: "sensor-data",
    label: "Sensor Data",
    motion: "pulse",
    modes: ["expert"],
    path: "/sensor-data",
    roles: ["admin", "engineer"],
  },
  {
    description: "Preview, map, validate, and confirm bounded CSV imports.",
    icon: "sensor-data",
    label: "Data Onboarding",
    motion: "lift",
    modes: ["expert"],
    path: "/sensor-data/onboarding",
    roles: ["admin", "engineer"],
  },
  {
    description: "Recent import quality, freshness, and blocking issues.",
    icon: "monitoring",
    label: "Data Quality",
    motion: "pulse",
    modes: ["expert"],
    path: "/sensor-data/quality",
    roles: ["admin", "engineer"],
  },
  {
    description: "Use-case templates and a grounded training readiness gate.",
    icon: "training-jobs",
    label: "Guided AI",
    motion: "glow",
    modes: ["expert"],
    path: "/guided-ai",
    roles: ["admin", "engineer"],
  },
  {
    description: "Authorized immutable datasets and document versions.",
    icon: "datasets",
    label: "Dataset Registry",
    motion: "lift",
    modes: ["expert"],
    path: "/datasets",
    roles: ["admin", "engineer"],
  },
  {
    description: "Background model training execution.",
    icon: "training-jobs",
    label: "Training Jobs",
    motion: "progress",
    modes: ["expert"],
    path: "/training",
    roles: ["admin", "engineer"],
  },
  {
    description: "Bounded algorithm search and cross-validation studies.",
    icon: "automl",
    label: "AutoML Studio",
    motion: "progress",
    modes: ["expert"],
    path: "/automl",
    roles: ["admin", "engineer"],
  },
  {
    description: "Registered models and immutable versions.",
    icon: "models",
    label: "Models",
    motion: "lift",
    modes: ["expert"],
    path: "/models",
    roles: ["admin", "engineer"],
  },
  {
    description: "Held-out metrics, plots, and model explanations.",
    icon: "monitoring",
    label: "Evaluation Studio",
    motion: "chart-rise",
    modes: ["expert"],
    path: "/evaluations",
    roles: ["admin", "engineer"],
  },
  {
    description: "Run and inspect registered-model predictions.",
    icon: "predictions",
    label: "Predictions",
    motion: "chart-rise",
    modes: ["expert"],
    path: "/predictions",
    roles: ["admin", "engineer"],
  },
  {
    description: "Grounded indexes over registered document datasets.",
    icon: "knowledge",
    label: "Knowledge Bases",
    motion: "glow",
    modes: ["expert"],
    path: "/knowledge",
    roles: ["admin", "engineer"],
  },
  {
    description: "Citation-aware answers from authorized registered evidence.",
    icon: "chat",
    label: "AI Assistant",
    motion: "pop",
    modes: ["expert"],
    path: "/chat",
    roles: ["admin", "engineer"],
  },
  {
    description: "Model health, data quality, and drift.",
    icon: "monitoring",
    label: "Monitoring",
    motion: "pulse",
    modes: ["expert"],
    path: "/monitoring",
    roles: ["admin", "engineer"],
  },
  {
    description: "Controlled retraining policies and request lifecycle.",
    icon: "retraining",
    label: "Retraining",
    motion: "rotate",
    modes: ["expert"],
    path: "/retraining",
    roles: ["admin", "engineer"],
  },
  {
    description: "Governance decisions and operational history.",
    icon: "audit",
    label: "Audit Logs",
    motion: "flow",
    modes: ["expert"],
    path: "/audit-log",
    roles: ["admin", "engineer"],
  },
  {
    description: "Company-scoped roles and account lifecycle.",
    icon: "users",
    label: "Users",
    motion: "lift",
    modes: ["expert"],
    path: "/users",
    roles: ["admin"],
  },
  {
    description: "Platform and workspace preferences.",
    icon: "settings",
    label: "Settings",
    motion: "rotate",
    path: "/settings",
  },
  {
    description: "Control deterministic, bounded factory demonstration scenarios.",
    feature: "demo",
    icon: "factories",
    label: "Demo Control",
    motion: "progress",
    path: "/demo/control",
    roles: ["admin", "engineer"],
  },
  {
    description: "Grounded management metrics and operational drill-downs.",
    icon: "dashboard",
    label: "Executive Dashboard",
    motion: "chart-rise",
    path: "/executive",
    roles: ["admin"],
  },
  {
    description: "Generate and download bounded authorized report exports.",
    icon: "audit",
    label: "Reports",
    motion: "lift",
    path: "/reports",
    roles: ["admin"],
  },
  {
    description: "Authenticated account identity and workspace access.",
    icon: "users",
    label: "My Profile",
    motion: "lift",
    path: "/profile",
    sidebar: false,
  },
  {
    description: "Submit a bounded authenticated support request.",
    icon: "chat",
    label: "Contact Support",
    motion: "pop",
    path: "/support",
    sidebar: false,
  },
];

export function getVisibleNavigationItems(
  role: NavigationRole | null,
  mode: NavigationMode,
  features: {
    readonly demo_tools_enabled: boolean;
    readonly operations_workflow_enabled: boolean;
  },
): readonly NavigationItem[] {
  return navigationItems.filter(
    (item) =>
      (item.roles === undefined ||
        (role !== null && hasLegacyRoleAccess(role, item.roles))) &&
      item.sidebar !== false &&
      (item.modes === undefined || item.modes.includes(mode)) &&
      (item.feature !== "operations" || features.operations_workflow_enabled) &&
      (item.feature !== "demo" || features.demo_tools_enabled),
  );
}

export function getNavigationItem(pathname: string): NavigationItem {
  return (
    navigationItems
      .filter(
        (item) =>
          item.path === pathname ||
          (item.path !== "/" && pathname.startsWith(`${item.path}/`)),
      )
      .sort((left, right) => right.path.length - left.path.length)[0] ??
    navigationItems[0]
  );
}
