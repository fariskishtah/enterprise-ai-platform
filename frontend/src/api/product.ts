import { apiRequest } from "./client";

export interface ProductFeatureFlags {
  readonly demo_tools_enabled: boolean;
  readonly operations_workflow_enabled: boolean;
  readonly simplified_experience_enabled: boolean;
}

export function getProductFeatureFlags(
  signal?: AbortSignal,
): Promise<ProductFeatureFlags> {
  return apiRequest("/product/features", { signal });
}
