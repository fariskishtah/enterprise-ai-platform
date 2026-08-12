"""Central six-role authorization policy."""

from __future__ import annotations

from enum import StrEnum

from app.models.user import UserRole


class Permission(StrEnum):
    """Stable capabilities used by backend authorization dependencies."""

    PLATFORM_READ = "platform.read"
    ENGINEERING_READ = "engineering.read"
    ENGINEERING_WRITE = "engineering.write"
    OPERATIONS_EXECUTE = "operations.execute"
    TENANT_ADMINISTER = "tenant.administer"
    TEAM_VIEW = "team.view"
    TEAM_MANAGE = "team.manage"
    OWNER_ASSIGN = "owner.assign"
    BILLING_MANAGE = "billing.manage"
    BILLING_PLATFORM_OPERATE = "billing.platform_operate"
    AUDIT_READ = "audit.read"


PLATFORM_ONLY_PERMISSIONS = frozenset({Permission.BILLING_PLATFORM_OPERATE})


ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.OWNER: frozenset(set(Permission) - PLATFORM_ONLY_PERMISSIONS),
    UserRole.ADMIN: frozenset(
        {
            Permission.PLATFORM_READ,
            Permission.ENGINEERING_READ,
            Permission.ENGINEERING_WRITE,
            Permission.OPERATIONS_EXECUTE,
            Permission.TENANT_ADMINISTER,
            Permission.TEAM_VIEW,
            Permission.TEAM_MANAGE,
            Permission.BILLING_MANAGE,
            Permission.AUDIT_READ,
        }
    ),
    UserRole.ENGINEER: frozenset(
        {
            Permission.PLATFORM_READ,
            Permission.ENGINEERING_READ,
            Permission.ENGINEERING_WRITE,
            Permission.OPERATIONS_EXECUTE,
        }
    ),
    UserRole.OPERATOR: frozenset(
        {Permission.PLATFORM_READ, Permission.OPERATIONS_EXECUTE}
    ),
    UserRole.ANALYST: frozenset(
        {
            Permission.PLATFORM_READ,
            Permission.ENGINEERING_READ,
            Permission.AUDIT_READ,
        }
    ),
    UserRole.VIEWER: frozenset({Permission.PLATFORM_READ}),
}


def has_permissions(
    role: UserRole,
    *required: Permission,
    is_platform_operator: bool = False,
) -> bool:
    """Return whether a role owns every requested capability."""
    requested = set(required)
    platform_requested = requested & PLATFORM_ONLY_PERMISSIONS
    if platform_requested and not is_platform_operator:
        return False
    tenant_requested = requested - PLATFORM_ONLY_PERMISSIONS
    return tenant_requested.issubset(ROLE_PERMISSIONS[role])


def is_tenant_administrator(role: UserRole) -> bool:
    """Return whether a role inherits tenant-administrator scope."""
    return has_permissions(role, Permission.TENANT_ADMINISTER)


def legacy_route_permission(
    allowed_roles: tuple[UserRole, ...], *, safe_method: bool
) -> Permission:
    """Map existing route declarations onto the centralized capability model.

    This compatibility bridge lets Owner inherit Admin access and gives Analyst
    and Viewer read-only access without granting either role legacy mutations.
    New endpoints should use explicit permissions directly.
    """
    if UserRole.OPERATOR in allowed_roles:
        return (
            Permission.PLATFORM_READ if safe_method else Permission.OPERATIONS_EXECUTE
        )
    if UserRole.ENGINEER in allowed_roles:
        return (
            Permission.ENGINEERING_READ if safe_method else Permission.ENGINEERING_WRITE
        )
    return Permission.TENANT_ADMINISTER
