"""
UAE v3 — FastAPI Auth Dependencies

FastAPI dependency functions for route-level authentication and authorization.

Usage in route:
    @router.post("/claims")
    async def create_claim(
        body: ClaimRequest,
        auth: AuthContext = Depends(require_permission("claims:create")),
        db: AsyncSession = Depends(get_async_session),
    ):
        ...

Auth is extracted from:
  - Authorization: Bearer <jwt>
  - X-API-Key: <raw_key>

If UAE_AUTH_ENABLED=false (dev mode), all requests get admin context.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader

from core.auth.auth_service import AuthContext, AuthError, get_auth_service
from core.auth.roles import Role

logger = logging.getLogger(__name__)

# Security schemes
_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Allow disabling auth for development/testing
_AUTH_ENABLED = os.environ.get("UAE_AUTH_ENABLED", "true").lower() not in ("false", "0", "no")

if not _AUTH_ENABLED:
    logger.warning(
        "UAE_AUTH_ENABLED=false — all requests will be granted admin access. "
        "This is NOT safe for production."
    )


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    api_key: Optional[str] = Security(_api_key_header),
) -> AuthContext:
    """
    Core FastAPI dependency — resolves AuthContext from request credentials.
    Raises HTTP 401 if no valid credentials.
    """
    if not _AUTH_ENABLED:
        return AuthContext(
            user_id="dev-admin",
            role=Role.ADMIN,
            node_id=None,
            auth_method="dev_bypass",
        )

    auth = get_auth_service()
    bearer_token = credentials.credentials if credentials else None

    try:
        return auth.authenticate_request(bearer_token=bearer_token, api_key=api_key)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_permission(permission: str) -> Callable:
    """
    Dependency factory — returns a dependency that enforces a permission.

    Usage:
        auth = Depends(require_permission("claims:verify"))
    """
    async def _check(
        auth_ctx: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if not _AUTH_ENABLED:
            return auth_ctx
        svc = get_auth_service()
        try:
            svc.require(auth_ctx, permission)
        except AuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )
        return auth_ctx
    return _check


def require_role(required_role: Role) -> Callable:
    """Dependency factory — enforces a minimum role."""
    async def _check(
        auth_ctx: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if not _AUTH_ENABLED:
            return auth_ctx
        svc = get_auth_service()
        try:
            svc.require_role(auth_ctx, required_role)
        except AuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )
        return auth_ctx
    return _check


def require_admin() -> Callable:
    """Shortcut dependency for admin-only endpoints."""
    return require_role(Role.ADMIN)


def require_federation_node() -> Callable:
    """Dependency for federation transport endpoints."""
    return require_role(Role.FEDERATION_NODE)
