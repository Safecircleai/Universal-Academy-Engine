"""
UAE v3 — JWT Service

Issues and validates JWT tokens for human users.
Service-to-service federation auth uses signed messages (see message_signing.py),
not JWT.

Token structure:
  {
    "sub": "<user_id>",
    "role": "<role>",
    "node_id": "<node_id>",    # which node issued this token
    "iat": <issued_at_unix>,
    "exp": <expires_at_unix>,
    "jti": "<unique_token_id>" # for revocation checks
  }

Configuration via environment:
  UAE_JWT_SECRET    — HMAC-SHA256 secret (min 32 bytes)
  UAE_JWT_ALGORITHM — Default: HS256
  UAE_JWT_TTL_SECS  — Token lifetime in seconds (default: 3600)

For production, consider RS256 with key pairs instead of HS256.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import jwt as pyjwt
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False
    logger.warning("PyJWT not installed. JWT auth will be non-functional. Run: pip install PyJWT")

from core.auth.roles import Role


class JWTError(Exception):
    """Raised when JWT issuance or validation fails."""


class JWTService:
    """Issues and validates JWT tokens."""

    def __init__(
        self,
        secret: Optional[str] = None,
        algorithm: str = "HS256",
        ttl_seconds: int = 3600,
    ) -> None:
        self.secret = secret or os.environ.get("UAE_JWT_SECRET", "change-me-in-production-32bytes")
        self.algorithm = algorithm or os.environ.get("UAE_JWT_ALGORITHM", "HS256")
        self.ttl_seconds = int(os.environ.get("UAE_JWT_TTL_SECS", str(ttl_seconds)))

        if self.secret == "change-me-in-production-32bytes":
            logger.warning("JWT secret is the default value. Set UAE_JWT_SECRET in production.")

    def issue_token(
        self,
        user_id: str,
        role: Role,
        *,
        node_id: Optional[str] = None,
        extra_claims: Optional[dict] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """Issue a signed JWT token."""
        if not _JWT_AVAILABLE:
            raise JWTError("PyJWT not installed. Cannot issue tokens.")

        now = datetime.now(timezone.utc)
        ttl = ttl_seconds or self.ttl_seconds
        payload = {
            "sub": user_id,
            "role": role.value,
            "node_id": node_id,
            "iat": now,
            "exp": now + timedelta(seconds=ttl),
            "jti": str(uuid.uuid4()),
        }
        if extra_claims:
            payload.update(extra_claims)

        token = pyjwt.encode(payload, self.secret, algorithm=self.algorithm)
        logger.info("Issued JWT for user=%s role=%s node=%s", user_id, role.value, node_id)
        return token

    def validate_token(self, token: str) -> dict:
        """
        Validate and decode a JWT token.
        Returns the decoded payload dict.
        Raises JWTError on invalid/expired tokens.
        """
        if not _JWT_AVAILABLE:
            raise JWTError("PyJWT not installed. Cannot validate tokens.")

        try:
            payload = pyjwt.decode(
                token, self.secret, algorithms=[self.algorithm],
                options={"require": ["sub", "role", "exp", "jti"]},
            )
            return payload
        except pyjwt.ExpiredSignatureError:
            raise JWTError("Token has expired.")
        except pyjwt.InvalidTokenError as exc:
            raise JWTError(f"Invalid token: {exc}")

    def extract_role(self, token: str) -> Role:
        """Decode token and return the role claim."""
        payload = self.validate_token(token)
        role_str = payload.get("role", "")
        try:
            return Role(role_str)
        except ValueError:
            raise JWTError(f"Unknown role in token: {role_str!r}")

    def extract_user_id(self, token: str) -> str:
        """Decode token and return the subject (user_id)."""
        payload = self.validate_token(token)
        return payload["sub"]


# Module-level singleton — configured from environment at import time
_jwt_service: Optional[JWTService] = None


def get_jwt_service() -> JWTService:
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service
