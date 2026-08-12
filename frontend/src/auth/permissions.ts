import type { UserRole } from "./authApi";

export type ProductCapability =
  | "audit.read"
  | "billing.manage"
  | "engineering.read"
  | "engineering.write"
  | "operations.execute"
  | "platform.read"
  | "team.manage"
  | "tenant.administer";

const roleCapabilities: Readonly<Record<UserRole, ReadonlySet<ProductCapability>>> = {
  admin: new Set([
    "audit.read",
    "billing.manage",
    "engineering.read",
    "engineering.write",
    "operations.execute",
    "platform.read",
    "team.manage",
    "tenant.administer",
  ]),
  analyst: new Set(["audit.read", "engineering.read", "platform.read"]),
  engineer: new Set([
    "engineering.read",
    "engineering.write",
    "operations.execute",
    "platform.read",
  ]),
  operator: new Set(["operations.execute", "platform.read"]),
  owner: new Set([
    "audit.read",
    "billing.manage",
    "engineering.read",
    "engineering.write",
    "operations.execute",
    "platform.read",
    "team.manage",
    "tenant.administer",
  ]),
  viewer: new Set(["platform.read"]),
};

export function hasProductCapability(
  role: UserRole | null,
  capability: ProductCapability,
): boolean {
  return role !== null && roleCapabilities[role].has(capability);
}

export function roleDisplayName(role: UserRole): string {
  const names: Readonly<Record<UserRole, string>> = {
    admin: "Operations Manager",
    analyst: "Data Analyst",
    engineer: "Engineer / Data User",
    operator: "Operator",
    owner: "Factory Owner",
    viewer: "Viewer",
  };
  return names[role];
}

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
