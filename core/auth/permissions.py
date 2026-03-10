"""
UAE v3 — Permission Definitions

Maps operations to minimum required roles.
Every protected endpoint checks against this registry.

Permission keys follow the pattern: resource:action
  e.g., "claims:verify", "credentials:issue", "federation:publish"
"""

from __future__ import annotations

from core.auth.roles import Role

# Permission registry: permission_key -> minimum_role
PERMISSION_REGISTRY: dict[str, Role] = {
    # Sources
    "sources:read": Role.READ_ONLY,
    "sources:create": Role.CURRICULUM_OPERATOR,
    "sources:delete": Role.ADMIN,

    # Claims
    "claims:read": Role.READ_ONLY,
    "claims:create": Role.REVIEWER,
    "claims:update_status": Role.REVIEWER,
    "claims:verify": Role.REVIEWER,
    "claims:deprecate": Role.REVIEWER,
    "claims:delete": Role.ADMIN,

    # Knowledge graph
    "knowledge_graph:read": Role.READ_ONLY,
    "knowledge_graph:write": Role.CURRICULUM_OPERATOR,

    # Verification
    "verification:run": Role.REVIEWER,
    "verification:attestation:create": Role.REVIEWER,
    "verification:attestation:read": Role.READ_ONLY,

    # Courses / curriculum
    "courses:read": Role.READ_ONLY,
    "courses:create": Role.CURRICULUM_OPERATOR,
    "courses:publish": Role.CURRICULUM_OPERATOR,
    "courses:approve": Role.ADMIN,
    "courses:delete": Role.ADMIN,

    # Competencies
    "competencies:read": Role.READ_ONLY,
    "competencies:write": Role.CURRICULUM_OPERATOR,

    # Credentials
    "credentials:read": Role.AUDITOR,
    "credentials:issue": Role.ISSUER,
    "credentials:revoke": Role.ISSUER,

    # Audit
    "audit:read": Role.AUDITOR,
    "audit:run": Role.AUDITOR,
    "audit:export": Role.AUDITOR,

    # Federation (node management)
    "federation:nodes:read": Role.READ_ONLY,
    "federation:nodes:register": Role.ADMIN,
    "federation:nodes:policy_update": Role.ADMIN,
    "federation:claims:publish": Role.CURRICULUM_OPERATOR,
    "federation:claims:import": Role.CURRICULUM_OPERATOR,
    "federation:claims:contest": Role.REVIEWER,
    "federation:claims:adopt": Role.CURRICULUM_OPERATOR,
    "federation:transport:receive": Role.FEDERATION_NODE,
    "federation:transport:handshake": Role.FEDERATION_NODE,

    # Admin
    "admin:users": Role.ADMIN,
    "admin:keys": Role.ADMIN,
    "admin:settings": Role.ADMIN,
}


def get_required_role(permission: str) -> Role:
    """Return the minimum role required for a permission."""
    if permission not in PERMISSION_REGISTRY:
        raise ValueError(f"Unknown permission: {permission!r}")
    return PERMISSION_REGISTRY[permission]


def check_permission(role: Role, permission: str) -> bool:
    """Return True if role has the required permission."""
    from core.auth.roles import has_minimum_role
    required = get_required_role(permission)
    return has_minimum_role(role, required)
