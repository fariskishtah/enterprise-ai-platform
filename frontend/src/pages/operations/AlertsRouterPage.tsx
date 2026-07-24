import type { ReactElement } from "react";

import { useProductExperience } from "../../product/productExperience";
import { AlertDetailPage } from "../intelligence/AlertDetailPage";
import { AlertsPage } from "../intelligence/AlertsPage";
import { OperationalAlertDetailPage } from "./OperationalAlertDetailPage";
import { OperationalAlertsPage } from "./OperationalAlertsPage";

export function AlertsRouterPage(): ReactElement {
  const { features, mode } = useProductExperience();
  return mode === "simple" && features.operations_workflow_enabled ? (
    <OperationalAlertsPage />
  ) : (
    <AlertsPage />
  );
}

export function AlertDetailRouterPage(): ReactElement {
  const { features, mode } = useProductExperience();
  return mode === "simple" && features.operations_workflow_enabled ? (
    <OperationalAlertDetailPage />
  ) : (
    <AlertDetailPage />
  );
}
