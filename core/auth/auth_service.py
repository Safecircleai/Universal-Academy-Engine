"""
UAE v3 — Auth Service

Central authentication and authorization service.
Supports two authentication paths:
  1. JWT Bearer tokens (for human users)
  2. API Keys (for service accounts and federation nodes)

Authorization is role + permission based.
All auth-sensitive operations are logged for audit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.auth.api_keys import ApiKeyRecord, get_api_key_registry
from core.auth.jwt_service import JWTError, get_jwt_service
from core.auth.permissions import check_permission
from core.auth.roles import Role

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication or authorization fails."""


@dataclass
class AuthContext:
    """Authenticated identity for a request."""
    user_id: str
    role: Role
    node_id: Optional[str]
    auth_method: str        # "jwt" | "api_key"
    raw_token: Optional[str] = None


class AuthService:
    """
    Authenticates requests and checks permissions.

    Usage (in FastAPI dependency):
        context = auth_service.authenticate_bearer(token)
        auth_service.require(context, "claims:verify")
    """

    def __init__(self) -> None:
        self._jwt = get_jwt_service()
        self._keys = get_api_key_registry()

    def authenticate_bearer(self, token: str) -> AuthContext:
        """Authenticate a Bearer JWT token."""
        try:
            payload = self._jwt.validate_token(token)
            role = Role(payload["role"])
            ctx = AuthContext(
                user_id=payload["sub"],
                role=role,
                node_id=payload.get("node_id"),
                auth_method="jwt",
                raw_token=token,
            )
            logger.debug("JWT auth OK: user=%s role=%s", ctx.user_id, ctx.role.value)
            return ctx
        except (JWTError, ValueError) as exc:
            raise AuthError(f"JWT authentication failed: {exc}") from exc

    def authenticate_api_key(self, raw_key: str) -> AuthContext:
        """Authenticate an API key from X-API-Key header."""
        record = self._keys.lookup(raw_key)
        if record is None:
            raise AuthError("Invalid or revoked API key.")
        ctx = AuthContext(
            user_id=f"apikey:{record.name}",
            role=record.role,
            node_id=record.node_id,
            auth_method="api_key",
        )
        logger.debug("API key auth OK: name=%s role=%s", record.name, record.role.value)
        return ctx

    def authenticate_request(
        self,
        *,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> AuthContext:
        """
        Authenticate from either Bearer token or API key.
        JWT takes precedence if both are provided.
        Raises AuthError if neither succeeds.
        """
        if bearer_token:
            return self.authenticate_bearer(bearer_token)
        if api_key:
            return self.authenticate_api_key(api_key)
        raise AuthError("No authentication credentials provided.")

    def require(self, context: AuthContext, permission: str) -> None:
        """
        Assert that the authenticated context has the given permission.
        Raises AuthError (403) if not.
        """
        if not check_permission(context.role, permission):
            logger.warning(
                "Authorization denied: user=%s role=%s permission=%s",
                context.user_id, context.role.value, permission,
            )
            raise AuthError(
                f"Role {context.role.value!r} does not have permission {permission!r}."
            )
        logger.debug(
            "Authorization granted: user=%s role=%s permission=%s",
            context.user_id, context.role.value, permission,
        )

    def require_role(self, context: AuthContext, required_role: Role) -> None:
        """Assert minimum role level."""
        from core.auth.roles import has_minimum_role
        if not has_minimum_role(context.role, required_role):
            raise AuthError(
                f"Required role {required_role.value!r}, "
                f"got {context.role.value!r}."
            )


# Module-level singleton
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
