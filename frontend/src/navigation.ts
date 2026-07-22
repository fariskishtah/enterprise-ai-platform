export type NavigationRole = "admin" | "engineer" | "operator";

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
  | "training-jobs"
  | "users";

export interface NavigationItem {
  readonly description: string;
  readonly icon: NavigationIcon;
  readonly label: string;
  readonly path: string;
  readonly roles?: readonly NavigationRole[];
}

export const navigationItems: readonly NavigationItem[] = [
  {
    description: "Operational overview and platform status.",
    icon: "dashboard",
    label: "Dashboard",
    path: "/",
  },
  {
    description: "Manufacturing sites and production hierarchy.",
    icon: "factories",
    label: "Factories",
    path: "/factories",
  },
  {
    description: "Sensor readings and ingestion activity.",
    icon: "sensor-data",
    label: "Sensor Data",
    path: "/sensor-data",
  },
  {
    description: "Authorized immutable datasets and document versions.",
    icon: "datasets",
    label: "Dataset Registry",
    path: "/datasets",
    roles: ["admin", "engineer"],
  },
  {
    description: "Background model training execution.",
    icon: "training-jobs",
    label: "Training Jobs",
    path: "/training",
    roles: ["admin", "engineer"],
  },
  {
    description: "Bounded algorithm search and cross-validation studies.",
    icon: "automl",
    label: "AutoML Studio",
    path: "/automl",
    roles: ["admin", "engineer"],
  },
  {
    description: "Registered models and immutable versions.",
    icon: "models",
    label: "Models",
    path: "/models",
  },
  {
    description: "Held-out metrics, plots, and model explanations.",
    icon: "monitoring",
    label: "Evaluation Studio",
    path: "/evaluations",
    roles: ["admin", "engineer"],
  },
  {
    description: "Run and inspect registered-model predictions.",
    icon: "predictions",
    label: "Predictions",
    path: "/predictions",
  },
  {
    description: "Grounded indexes over registered document datasets.",
    icon: "knowledge",
    label: "Knowledge Bases",
    path: "/knowledge",
    roles: ["admin", "engineer"],
  },
  {
    description: "Citation-aware answers from authorized registered evidence.",
    icon: "chat",
    label: "AI Assistant",
    path: "/chat",
    roles: ["admin", "engineer"],
  },
  {
    description: "Model health, data quality, and drift.",
    icon: "monitoring",
    label: "Monitoring",
    path: "/monitoring",
  },
  {
    description: "Controlled retraining policies and request lifecycle.",
    icon: "retraining",
    label: "Retraining",
    path: "/retraining",
  },
  {
    description: "Governance decisions and operational history.",
    icon: "audit",
    label: "Audit Logs",
    path: "/audit-log",
    roles: ["admin", "engineer"],
  },
  {
    description: "User access and role administration.",
    icon: "users",
    label: "Users & Roles",
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

export function getNavigationItem(pathname: string): NavigationItem {
  return (
    navigationItems.find(
      (item) =>
        item.path === pathname ||
        (item.path !== "/" && pathname.startsWith(`${item.path}/`)),
    ) ?? navigationItems[0]
  );
}
