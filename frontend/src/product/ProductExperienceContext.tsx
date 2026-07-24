import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { isRequestCancelled } from "../api/client";
import { getProductFeatureFlags, type ProductFeatureFlags } from "../api/product";
import { useAuth } from "../auth/useAuth";
import {
  ProductExperienceContext,
  type ProductExperienceValue,
  type ProductMode,
} from "./productExperience";

const disabledFeatures: ProductFeatureFlags = {
  demo_tools_enabled: false,
  operations_workflow_enabled: false,
  simplified_experience_enabled: false,
};

interface FeatureState {
  readonly error: string | null;
  readonly features: ProductFeatureFlags;
  readonly userId: string | null;
}

function defaultMode(role: "admin" | "engineer" | "operator" | null): ProductMode {
  return role === "operator" ? "simple" : "expert";
}

function storageKey(userId: string): string {
  return `fk-product-mode:${userId}`;
}

export function ProductExperienceProvider({
  children,
}: {
  readonly children: ReactNode;
}): ReactElement {
  const { isAuthenticated, role, user } = useAuth();
  const [featureState, setFeatureState] = useState<FeatureState>({
    error: null,
    features: disabledFeatures,
    userId: null,
  });
  const [adminPreferences, setAdminPreferences] = useState<
    Readonly<Record<string, ProductMode>>
  >({});

  useEffect(() => {
    if (!isAuthenticated || user === null) {
      return;
    }
    const controller = new AbortController();
    let active = true;
    getProductFeatureFlags(controller.signal)
      .then((value) => {
        if (active) {
          setFeatureState({
            error: null,
            features: value,
            userId: user.id,
          });
        }
      })
      .catch((error: unknown) => {
        if (active && !isRequestCancelled(error, controller.signal)) {
          setFeatureState({
            error:
              "Product experience controls are unavailable. Optional features are disabled.",
            features: disabledFeatures,
            userId: user.id,
          });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [isAuthenticated, user]);

  const hasCurrentFeatures =
    isAuthenticated && user !== null && featureState.userId === user.id;
  const effectiveFeatures = hasCurrentFeatures
    ? featureState.features
    : disabledFeatures;
  const featureError = hasCurrentFeatures ? featureState.error : null;
  const featuresLoading = isAuthenticated && user !== null && !hasCurrentFeatures;
  const canSwitchMode =
    role === "admin" && effectiveFeatures.simplified_experience_enabled;
  const storedAdminPreference =
    role === "admin" && user !== null
      ? (adminPreferences[user.id] ??
        (localStorage.getItem(storageKey(user.id)) === "simple" ? "simple" : "expert"))
      : "expert";
  const mode =
    role === "operator"
      ? "simple"
      : role === "engineer"
        ? "expert"
        : canSwitchMode
          ? storedAdminPreference
          : defaultMode(role);

  const setMode = useCallback(
    (nextMode: ProductMode): void => {
      if (
        role !== "admin" ||
        user === null ||
        !effectiveFeatures.simplified_experience_enabled
      ) {
        return;
      }
      localStorage.setItem(storageKey(user.id), nextMode);
      setAdminPreferences((current) => ({ ...current, [user.id]: nextMode }));
    },
    [effectiveFeatures.simplified_experience_enabled, role, user],
  );

  const value = useMemo<ProductExperienceValue>(
    () => ({
      canSwitchMode,
      featureError,
      features: effectiveFeatures,
      featuresLoading,
      mode,
      setMode,
    }),
    [canSwitchMode, featureError, effectiveFeatures, featuresLoading, mode, setMode],
  );

  return (
    <ProductExperienceContext.Provider value={value}>
      {children}
    </ProductExperienceContext.Provider>
  );
}
