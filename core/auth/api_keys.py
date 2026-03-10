"""
UAE v3 — API Key Management

Static API keys for service-to-service and developer access.
Each key is associated with a role and optional node_id.

In production, keys are stored hashed (SHA-256) — raw keys are never persisted.
The caller presents the raw key in the Authorization header; the server hashes
it and looks it up in the registry.

Configuration:
  Keys are configured via environment variable UAE_API_KEYS as JSON:
  [
    {"key": "raw-key-value", "role": "admin", "name": "admin-key", "node_id": null},
    {"key": "fed-key",       "role": "federation_node", "name": "node-b", "node_id": "node-b-id"}
  ]

For production, prefer JWT tokens for human users.
API keys are best for: CI bots, federation node service accounts, monitoring.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Optional

from core.auth.roles import Role

logger = logging.getLogger(__name__)


@dataclass
class ApiKeyRecord:
    """A registered API key (stores hash, not raw key)."""
    key_hash: str           # SHA-256(raw_key)
    name: str               # human-readable label
    role: Role
    node_id: Optional[str]  # for federation_node keys
    is_active: bool = True


class ApiKeyRegistry:
    """
    In-memory registry of hashed API keys.
    Loads from UAE_API_KEYS environment variable on init.
    """

    def __init__(self) -> None:
        self._registry: dict[str, ApiKeyRecord] = {}  # key_hash -> record
        self._load_from_env()

    def _load_from_env(self) -> None:
        raw = os.environ.get("UAE_API_KEYS", "")
        if not raw:
            # Register a default admin key for dev (printed to logs)
            dev_key = os.environ.get("UAE_DEV_API_KEY", "dev-admin-key-change-me")
            self.register(dev_key, "dev-admin", Role.ADMIN)
            logger.warning(
                "UAE_API_KEYS not set. Registered default dev admin key. "
                "Set UAE_API_KEYS in production."
            )
            return

        try:
            entries = json.loads(raw)
            for entry in entries:
                self.register(
                    entry["key"],
                    entry.get("name", "unnamed"),
                    Role(entry["role"]),
                    node_id=entry.get("node_id"),
                )
            logger.info("Loaded %d API keys from UAE_API_KEYS", len(entries))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Failed to parse UAE_API_KEYS: %s", exc)

    def register(
        self,
        raw_key: str,
        name: str,
        role: Role,
        *,
        node_id: Optional[str] = None,
    ) -> str:
        """Register a key. Returns the SHA-256 hash (never stores raw key)."""
        key_hash = _hash_key(raw_key)
        self._registry[key_hash] = ApiKeyRecord(
            key_hash=key_hash,
            name=name,
            role=role,
            node_id=node_id,
        )
        return key_hash

    def lookup(self, raw_key: str) -> Optional[ApiKeyRecord]:
        """Look up a key by raw value. Returns None if not found or inactive."""
        key_hash = _hash_key(raw_key)
        record = self._registry.get(key_hash)
        if record and record.is_active:
            return record
        return None

    def revoke(self, raw_key: str) -> bool:
        """Deactivate a key. Returns True if found."""
        key_hash = _hash_key(raw_key)
        if key_hash in self._registry:
            self._registry[key_hash].is_active = False
            logger.warning("API key revoked: %s", self._registry[key_hash].name)
            return True
        return False

    @staticmethod
    def generate() -> str:
        """Generate a cryptographically secure API key."""
        return f"uae_{secrets.token_urlsafe(32)}"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# Module-level singleton
_registry: Optional[ApiKeyRegistry] = None


def get_api_key_registry() -> ApiKeyRegistry:
    global _registry
    if _registry is None:
        _registry = ApiKeyRegistry()
    return _registry
