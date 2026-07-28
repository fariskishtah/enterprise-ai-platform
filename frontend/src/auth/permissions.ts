import type { UserRole } from "./authApi";

export function hasLegacyRoleAccess(
  role: UserRole,
  allowed: readonly UserRole[],
): boolean {
  const compatibilityRole: UserRole =
    role === "owner"
      ? "admin"
      : role === "analyst"
        ? "engineer"
        : role === "viewer"
          ? "operator"
          : role;
  return allowed.includes(role) || allowed.includes(compatibilityRole);
}
