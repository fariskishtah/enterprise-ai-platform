import {
  hasLegacyRoleAccess,
  hasProductCapability,
  type ProductCapability,
} from "./auth/permissions";
import type { UserRole } from "./auth/authApi";

export type NavigationRole = UserRole;
export type NavigationMode = "expert" | "simple";
export type NavigationFeature = "demo" | "operations";
export type NavigationGroup =
  | "overview"
  | "operations"
  | "ai-knowledge"
  | "advanced-ai"
  | "monitoring"
  | "administration"
  | "commercial";
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
  readonly capability?: ProductCapability;
  readonly description: string;
  readonly feature?: NavigationFeature;
  readonly group: NavigationGroup;
  readonly icon: NavigationIcon;
  readonly label: string;
  readonly motion: NavigationMotion;
  readonly modes?: readonly NavigationMode[];
  readonly path: string;
  readonly roles?: readonly NavigationRole[];
  readonly sidebar?: boolean;
}

export interface NavigationSection {
  readonly description: string;
  readonly id: NavigationGroup;
  readonly label: string;
}

export interface VisibleNavigationSection extends NavigationSection {
  readonly items: readonly NavigationItem[];
}

export const navigationSections: readonly NavigationSection[] = [
  { description: "Your starting point", id: "overview", label: "Overview" },
  {
    description: "Factories, equipment, work, and operational data",
    id: "operations",
    label: "Operations",
  },
  {
    description: "Guided, grounded AI workflows",
    id: "ai-knowledge",
    label: "AI & Knowledge",
  },
  {
    description: "Technical model development tools",
    id: "advanced-ai",
    label: "Advanced AI",
  },
  {
    description: "Health, performance, and reports",
    id: "monitoring",
    label: "Monitoring",
  },
  {
    description: "People, governance, and workspace controls",
    id: "administration",
    label: "Administration",
  },
  {
    description: "Plan, usage, and billing",
    id: "commercial",
    label: "Commercial",
  },
];

export const navigationItems: readonly NavigationItem[] = [
  {
    description: "Operational overview and platform status.",
    group: "overview",
    icon: "dashboard",
    label: "Overview",
    motion: "chart-rise",
    path: "/dashboard",
  },
  {
    description: "Manufacturing sites and production hierarchy.",
    group: "operations",
    icon: "factories",
    label: "Factories & Assets",
    motion: "lift",
    path: "/factories",
  },
  {
    description: "Machines available in your authorized factories.",
    group: "operations",
    icon: "factories",
    label: "Machines & Sensors",
    motion: "rotate",
    modes: ["simple"],
    path: "/machines",
  },
  {
    description: "Prioritized maintenance and operational work.",
    feature: "operations",
    group: "operations",
    icon: "audit",
    label: "Required Actions",
    motion: "pop",
    modes: ["simple"],
    path: "/operations/actions",
  },
  {
    description: "Open machine and monitoring conditions requiring attention.",
    feature: "operations",
    group: "operations",
    icon: "monitoring",
    label: "Alerts",
    motion: "shake",
    modes: ["simple"],
    path: "/monitoring/alerts",
  },
  {
    description: "Recent operational events across authorized factories.",
    feature: "operations",
    group: "operations",
    icon: "audit",
    label: "Activity",
    motion: "flow",
    modes: ["simple"],
    path: "/activity",
  },
  {
    description: "Active shifts, unresolved work, and handover history.",
    feature: "operations",
    group: "operations",
    icon: "audit",
    label: "Shift Handover",
    motion: "flow",
    modes: ["simple"],
    path: "/operations/shifts",
  },
  {
    description: "Sensor readings and ingestion activity.",
    group: "operations",
    icon: "sensor-data",
    label: "Machine & Sensor Data",
    motion: "pulse",
    modes: ["expert"],
    path: "/sensor-data",
    roles: ["admin", "engineer"],
  },
  {
    capability: "engineering.write",
    description: "Preview, map, validate, and confirm bounded CSV imports.",
    group: "operations",
    icon: "sensor-data",
    label: "Data Onboarding",
    motion: "lift",
    modes: ["expert"],
    path: "/sensor-data/onboarding",
    roles: ["admin", "engineer"],
  },
  {
    description: "Recent import quality, freshness, and blocking issues.",
    group: "operations",
    icon: "monitoring",
    label: "Data Quality",
    motion: "pulse",
    modes: ["expert"],
    path: "/sensor-data/quality",
    roles: ["admin", "engineer"],
  },
  {
    capability: "engineering.write",
    description: "Use-case templates and a grounded training readiness gate.",
    group: "ai-knowledge",
    icon: "training-jobs",
    label: "Guided AI",
    motion: "glow",
    modes: ["expert"],
    path: "/guided-ai",
    roles: ["admin", "engineer"],
  },
  {
    description: "Authorized immutable datasets and document versions.",
    group: "advanced-ai",
    icon: "datasets",
    label: "Datasets",
    motion: "lift",
    modes: ["expert"],
    path: "/datasets",
    roles: ["admin", "engineer"],
  },
  {
    description: "Background model training execution.",
    group: "advanced-ai",
    icon: "training-jobs",
    label: "Model Training",
    motion: "progress",
    modes: ["expert"],
    path: "/training",
    roles: ["admin", "engineer"],
  },
  {
    description: "Bounded algorithm search and cross-validation studies.",
    group: "advanced-ai",
    icon: "automl",
    label: "Automated Model Search",
    motion: "progress",
    modes: ["expert"],
    path: "/automl",
    roles: ["admin", "engineer"],
  },
  {
    description: "Registered models and immutable versions.",
    group: "ai-knowledge",
    icon: "models",
    label: "Models",
    motion: "lift",
    modes: ["expert"],
    path: "/models",
    roles: ["admin", "engineer"],
  },
  {
    description: "Held-out metrics, plots, and model explanations.",
    group: "advanced-ai",
    icon: "monitoring",
    label: "Model Evaluation",
    motion: "chart-rise",
    modes: ["expert"],
    path: "/evaluations",
    roles: ["admin", "engineer"],
  },
  {
    description: "Run and inspect registered-model predictions.",
    group: "ai-knowledge",
    icon: "predictions",
    label: "Predictions",
    motion: "chart-rise",
    modes: ["expert"],
    path: "/predictions",
    roles: ["admin", "engineer"],
  },
  {
    description: "Grounded indexes over registered document datasets.",
    group: "ai-knowledge",
    icon: "knowledge",
    label: "Knowledge Bases",
    motion: "glow",
    modes: ["expert"],
    path: "/knowledge",
    roles: ["admin", "engineer"],
  },
  {
    description: "Citation-aware answers from authorized registered evidence.",
    group: "ai-knowledge",
    icon: "chat",
    label: "AI Assistant",
    motion: "pop",
    modes: ["expert"],
    path: "/chat",
    roles: ["admin", "engineer"],
  },
  {
    description: "Model health, data quality, and drift.",
    group: "monitoring",
    icon: "monitoring",
    label: "Monitoring",
    motion: "pulse",
    modes: ["expert"],
    path: "/monitoring",
    roles: ["admin", "engineer"],
  },
  {
    description: "Controlled retraining policies and request lifecycle.",
    group: "advanced-ai",
    icon: "retraining",
    label: "Model Retraining",
    motion: "rotate",
    modes: ["expert"],
    path: "/retraining",
    roles: ["admin", "engineer"],
  },
  {
    description: "Governance decisions and operational history.",
    group: "administration",
    icon: "audit",
    label: "Audit History",
    motion: "flow",
    modes: ["expert"],
    path: "/audit-log",
    capability: "audit.read",
  },
  {
    description: "Company-scoped roles and account lifecycle.",
    group: "administration",
    icon: "users",
    label: "Users",
    motion: "lift",
    modes: ["expert"],
    path: "/users",
    roles: ["admin"],
  },
  {
    description: "Platform and workspace preferences.",
    group: "administration",
    icon: "settings",
    label: "Settings",
    motion: "rotate",
    path: "/settings",
  },
  {
    description: "Subscription, plan limits, payments, and invoices.",
    group: "commercial",
    icon: "audit",
    label: "Plan & Billing",
    motion: "flow",
    path: "/settings/billing",
    roles: ["admin"],
  },
  {
    description: "Control deterministic, bounded factory demonstration scenarios.",
    feature: "demo",
    group: "administration",
    icon: "factories",
    label: "Demo Control",
    motion: "progress",
    path: "/demo/control",
    roles: ["admin", "engineer"],
  },
  {
    description: "Grounded management metrics and operational drill-downs.",
    group: "overview",
    icon: "dashboard",
    label: "Executive Overview",
    motion: "chart-rise",
    path: "/executive",
    roles: ["admin"],
  },
  {
    description: "Generate and download bounded authorized report exports.",
    group: "monitoring",
    icon: "audit",
    label: "Reports",
    motion: "lift",
    path: "/reports",
    roles: ["admin"],
  },
  {
    description: "Authenticated account identity and workspace access.",
    group: "administration",
    icon: "users",
    label: "My Profile",
    motion: "lift",
    path: "/profile",
    sidebar: false,
  },
  {
    description: "Submit a bounded authenticated support request.",
    group: "administration",
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
      (item.capability === undefined || hasProductCapability(role, item.capability)) &&
      item.sidebar !== false &&
      (item.modes === undefined || item.modes.includes(mode)) &&
      (item.feature !== "operations" || features.operations_workflow_enabled) &&
      (item.feature !== "demo" || features.demo_tools_enabled),
  );
}

export function getVisibleNavigationSections(
  role: NavigationRole | null,
  mode: NavigationMode,
  features: {
    readonly demo_tools_enabled: boolean;
    readonly operations_workflow_enabled: boolean;
  },
): readonly VisibleNavigationSection[] {
  const items = getVisibleNavigationItems(role, mode, features);
  return navigationSections
    .map((section) => ({
      ...section,
      items: items.filter((item) => item.group === section.id),
    }))
    .filter((section) => section.items.length > 0);
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
