import { createContext, useContext } from "react";

import type { ProductFeatureFlags } from "../api/product";

export type ProductMode = "expert" | "simple";

export interface ProductExperienceValue {
  readonly canSwitchMode: boolean;
  readonly featureError: string | null;
  readonly features: ProductFeatureFlags;
  readonly featuresLoading: boolean;
  readonly mode: ProductMode;
  readonly setMode: (mode: ProductMode) => void;
}

export const ProductExperienceContext = createContext<ProductExperienceValue | null>(
  null,
);

export function useProductExperience(): ProductExperienceValue {
  const context = useContext(ProductExperienceContext);
  if (context === null) {
    throw new Error(
      "useProductExperience must be used within ProductExperienceProvider.",
    );
  }
  return context;
}
