"""
UAE v3 — Role Definitions

Roles are coarse-grained identities assigned to human users and service accounts.
Fine-grained access is controlled by permissions (see permissions.py).

Role hierarchy (higher index = more privilege):
  read_only < auditor < reviewer < issuer < curriculum_operator
  < federation_node < admin

federation_node is a peer role — not subordinate to admin.
Service-to-service federation auth uses the federation_node role.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """UAE role identifiers."""
    READ_ONLY = "read_only"
    AUDITOR = "auditor"
    REVIEWER = "reviewer"
    ISSUER = "issuer"
    CURRICULUM_OPERATOR = "curriculum_operator"
    # v4 doctrine roles
    DOCTRINE_STEWARD = "doctrine_steward"
    CONSTITUTIONAL_REVIEWER = "constitutional_reviewer"
    GOVERNANCE_COUNCIL = "governance_council"
    # Peer / service roles
    FEDERATION_NODE = "federation_node"
    ADMIN = "admin"


# Ordered by privilege level (ascending)
ROLE_HIERARCHY = [
    Role.READ_ONLY,
    Role.AUDITOR,
    Role.REVIEWER,
    Role.ISSUER,
    Role.CURRICULUM_OPERATOR,
    Role.DOCTRINE_STEWARD,
    Role.CONSTITUTIONAL_REVIEWER,
    Role.GOVERNANCE_COUNCIL,
    Role.ADMIN,
]

# federation_node is a peer role — not in the human hierarchy
PEER_ROLES = {Role.FEDERATION_NODE}


def role_level(role: Role) -> int:
    """Return privilege level (higher = more access). Peer roles return -1."""
    if role in PEER_ROLES:
        return -1
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return -1


def has_minimum_role(actual: Role, required: Role) -> bool:
    """Return True if actual role meets or exceeds required role level."""
    if required in PEER_ROLES:
        return actual == required or actual == Role.ADMIN
    if actual == Role.ADMIN:
        return True
    return role_level(actual) >= role_level(required)


# Human-readable role descriptions
ROLE_DESCRIPTIONS = {
    Role.READ_ONLY: "Can read sources, claims, courses, and credentials. No mutations.",
    Role.AUDITOR: "Read_only + can generate and view audit reports.",
    Role.REVIEWER: "Auditor + can verify claims and submit attestations.",
    Role.ISSUER: "Reviewer + can issue and revoke credentials.",
    Role.CURRICULUM_OPERATOR: "Issuer + can create/publish courses and manage curriculum.",
    Role.DOCTRINE_STEWARD: "Curriculum operator + can manage doctrine source classification and precedence.",
    Role.CONSTITUTIONAL_REVIEWER: "Doctrine steward + can conduct constitutional reviews of claims.",
    Role.GOVERNANCE_COUNCIL: "Constitutional reviewer + can record final governance decisions.",
    Role.FEDERATION_NODE: "Service account for inter-node federation transport.",
    Role.ADMIN: "Full access to all operations including node management.",
}
