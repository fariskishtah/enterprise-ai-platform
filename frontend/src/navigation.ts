export type NavigationRole = "admin" | "engineer" | "operator";

export type NavigationIcon =
  | "audit"
  | "dashboard"
  | "factories"
  | "models"
  | "monitoring"
  | "predictions"
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
    description: "Background model training execution.",
    icon: "training-jobs",
    label: "Training Jobs",
    path: "/training-jobs",
  },
  {
    description: "Registered models and immutable versions.",
    icon: "models",
    label: "Models",
    path: "/models",
  },
  {
    description: "Run and inspect registered-model predictions.",
    icon: "predictions",
    label: "Predictions",
    path: "/predictions",
  },
  {
    description: "Model health, data quality, and drift.",
    icon: "monitoring",
    label: "Monitoring",
    path: "/monitoring",
  },
  {
    description: "Governance decisions and operational history.",
    icon: "audit",
    label: "Audit Log",
    path: "/audit-log",
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
  return navigationItems.find((item) => item.path === pathname) ?? navigationItems[0];
}
