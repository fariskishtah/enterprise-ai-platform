export type NavigationRole = "admin" | "engineer" | "operator";
export type NavigationMode = "expert" | "simple";
export type NavigationFeature = "operations";

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
  readonly modes?: readonly NavigationMode[];
  readonly path: string;
  readonly roles?: readonly NavigationRole[];
}

export const navigationItems: readonly NavigationItem[] = [
  {
    description: "Operational overview and platform status.",
    icon: "dashboard",
    label: "Home",
    path: "/",
  },
  {
    description: "Manufacturing sites and production hierarchy.",
    icon: "factories",
    label: "Factory Overview",
    path: "/factories",
  },
  {
    description: "Machines available in your authorized factories.",
    icon: "factories",
    label: "Machines",
    modes: ["simple"],
    path: "/machines",
  },
  {
    description: "Prioritized maintenance and operational work.",
    feature: "operations",
    icon: "audit",
    label: "Required Actions",
    modes: ["simple"],
    path: "/operations/actions",
  },
  {
    description: "Open machine and monitoring conditions requiring attention.",
    feature: "operations",
    icon: "monitoring",
    label: "Alerts",
    modes: ["simple"],
    path: "/monitoring/alerts",
  },
  {
    description: "Recent operational events across authorized factories.",
    feature: "operations",
    icon: "audit",
    label: "Activity",
    modes: ["simple"],
    path: "/activity",
  },
  {
    description: "Active shifts, unresolved work, and handover history.",
    feature: "operations",
    icon: "audit",
    label: "Shift Handover",
    modes: ["simple"],
    path: "/operations/shifts",
  },
  {
    description: "Sensor readings and ingestion activity.",
    icon: "sensor-data",
    label: "Sensor Data",
    modes: ["expert"],
    path: "/sensor-data",
    roles: ["admin", "engineer"],
  },
  {
    description: "Authorized immutable datasets and document versions.",
    icon: "datasets",
    label: "Dataset Registry",
    modes: ["expert"],
    path: "/datasets",
    roles: ["admin", "engineer"],
  },
  {
    description: "Background model training execution.",
    icon: "training-jobs",
    label: "Training Jobs",
    modes: ["expert"],
    path: "/training",
    roles: ["admin", "engineer"],
  },
  {
    description: "Bounded algorithm search and cross-validation studies.",
    icon: "automl",
    label: "AutoML Studio",
    modes: ["expert"],
    path: "/automl",
    roles: ["admin", "engineer"],
  },
  {
    description: "Registered models and immutable versions.",
    icon: "models",
    label: "Models",
    modes: ["expert"],
    path: "/models",
    roles: ["admin", "engineer"],
  },
  {
    description: "Held-out metrics, plots, and model explanations.",
    icon: "monitoring",
    label: "Evaluation Studio",
    modes: ["expert"],
    path: "/evaluations",
    roles: ["admin", "engineer"],
  },
  {
    description: "Run and inspect registered-model predictions.",
    icon: "predictions",
    label: "Predictions",
    modes: ["expert"],
    path: "/predictions",
    roles: ["admin", "engineer"],
  },
  {
    description: "Grounded indexes over registered document datasets.",
    icon: "knowledge",
    label: "Knowledge Bases",
    modes: ["expert"],
    path: "/knowledge",
    roles: ["admin", "engineer"],
  },
  {
    description: "Citation-aware answers from authorized registered evidence.",
    icon: "chat",
    label: "AI Assistant",
    modes: ["expert"],
    path: "/chat",
    roles: ["admin", "engineer"],
  },
  {
    description: "Model health, data quality, and drift.",
    icon: "monitoring",
    label: "Monitoring",
    modes: ["expert"],
    path: "/monitoring",
    roles: ["admin", "engineer"],
  },
  {
    description: "Controlled retraining policies and request lifecycle.",
    icon: "retraining",
    label: "Retraining",
    modes: ["expert"],
    path: "/retraining",
    roles: ["admin", "engineer"],
  },
  {
    description: "Governance decisions and operational history.",
    icon: "audit",
    label: "Audit Logs",
    modes: ["expert"],
    path: "/audit-log",
    roles: ["admin", "engineer"],
  },
  {
    description: "Company-scoped roles and account lifecycle.",
    icon: "users",
    label: "Users",
    modes: ["expert"],
    path: "/users",
    roles: ["admin"],
  },
  {
    description: "Platform and workspace preferences.",
    icon: "settings",
    label: "Settings",
    path: "/settings",
  },
];

export function getVisibleNavigationItems(
  role: NavigationRole | null,
  mode: NavigationMode,
  features: { readonly operations_workflow_enabled: boolean },
): readonly NavigationItem[] {
  return navigationItems.filter(
    (item) =>
      (item.roles === undefined || (role !== null && item.roles.includes(role))) &&
      (item.modes === undefined || item.modes.includes(mode)) &&
      (item.feature !== "operations" || features.operations_workflow_enabled),
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
