"""
UAE v3 — Environment Key Provider

Reads private key material from environment variables.
Suitable for: containerised deployments where secrets are injected
              via environment (Docker secrets, Kubernetes secrets).

Environment variables:
  UAE_NODE_PRIVATE_KEY    — PEM-encoded RSA private key (or Ed25519)
  UAE_NODE_PUBLIC_KEY     — Corresponding PEM-encoded public key
  UAE_NODE_KEY_ALGORITHM  — Algorithm (default: RSA-SHA256)
  UAE_NODE_KEY_ID         — Logical key ID (default: "node-default")
  UAE_NODE_KEY_VERSION    — Key version string (default: "v1")

SECURITY NOTE:
  Never log or expose the private key value.
  In production, inject via orchestrator secrets — not .env files.
  Rotate by updating the environment variable and restarting the node.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from core.security.key_provider import KeyInfo, KeyProvider
from core.security.signing_service import sign_with_private_key_pem

logger = logging.getLogger(__name__)


class EnvKeyProvider(KeyProvider):
    """
    Reads key material from environment variables.
    Single-key provider — one signing key per node instance.
    For multi-key scenarios, use LocalKeyProvider or a KMS.
    """

    def __init__(self) -> None:
        self._key_id = os.environ.get("UAE_NODE_KEY_ID", "node-default")
        self._key_version = os.environ.get("UAE_NODE_KEY_VERSION", "v1")
        self._algorithm = os.environ.get("UAE_NODE_KEY_ALGORITHM", "RSA-SHA256")
        self._private_pem = os.environ.get("UAE_NODE_PRIVATE_KEY", "")
        self._public_pem = os.environ.get("UAE_NODE_PUBLIC_KEY", "")

        if not self._private_pem:
            logger.warning(
                "UAE_NODE_PRIVATE_KEY not set. EnvKeyProvider will use HMAC fallback. "
                "Set UAE_NODE_PRIVATE_KEY and UAE_NODE_PUBLIC_KEY for production."
            )

    def get_key_info(self, key_id: str) -> KeyInfo:
        self._assert_key_id(key_id)
        return self._build_info()

    def get_public_key_pem(self, key_id: str) -> str:
        self._assert_key_id(key_id)
        return self._public_pem or "DUMMY_PUBLIC_KEY"

    def sign(self, key_id: str, payload: bytes) -> bytes:
        self._assert_key_id(key_id)
        priv = self._private_pem or "DUMMY_PRIVATE_KEY"
        return sign_with_private_key_pem(priv, payload, self._algorithm)

    def list_active_keys(self) -> list[KeyInfo]:
        return [self._build_info()]

    def rotate_key(self, key_id: str) -> KeyInfo:
        """
        EnvKeyProvider does not support in-process rotation.
        Update the environment variable and restart the service.
        """
        raise NotImplementedError(
            "EnvKeyProvider does not support in-process key rotation. "
            "Update UAE_NODE_PRIVATE_KEY and UAE_NODE_PUBLIC_KEY, then restart the node."
        )

    def _assert_key_id(self, key_id: str) -> None:
        if key_id != self._key_id:
            raise KeyError(
                f"EnvKeyProvider only manages key {self._key_id!r}, "
                f"got request for {key_id!r}"
            )

    def _build_info(self) -> KeyInfo:
        return KeyInfo(
            key_id=self._key_id,
            key_version=self._key_version,
            algorithm=self._algorithm,
            public_key_pem=self._public_pem or "DUMMY_PUBLIC_KEY",
            created_at=datetime.now(timezone.utc),
            expires_at=None,
            is_active=True,
            provider_type="env",
        )
