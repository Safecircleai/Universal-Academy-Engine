"""
UAE v3 — Key Rotation Service

Manages key rotation lifecycle:
  - Triggers rotation on demand or by schedule
  - Keeps retired public keys available for verifying historical signatures
  - Tags signatures with key_version so verifiers know which key to use
  - Notifies federation peers of key changes via NodeHandshake refresh

Rotation should be performed:
  - On a schedule (e.g., every 90 days for production)
  - Immediately after a suspected compromise
  - When changing providers (local → KMS)

IMPORTANT: Never revoke a retired key's PUBLIC key from the registry
until you are certain no unverified historical signatures remain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.security.key_provider import KeyInfo, KeyProvider

logger = logging.getLogger(__name__)


@dataclass
class RotationEvent:
    """Record of a key rotation operation."""
    key_id: str
    old_version: str
    new_version: str
    rotated_at: datetime
    rotated_by: str
    reason: str


class KeyRotationService:
    """
    Coordinates key rotation across providers.

    Usage:
        service = KeyRotationService(provider)
        event = service.rotate("node-signing-key", reason="scheduled 90-day rotation")
    """

    def __init__(self, provider: KeyProvider) -> None:
        self.provider = provider
        self._rotation_history: list[RotationEvent] = []

    def rotate(
        self,
        key_id: str,
        *,
        reason: str = "manual rotation",
        rotated_by: str = "system",
    ) -> RotationEvent:
        """
        Rotate a key. Old key is archived; new key becomes active.
        Returns a RotationEvent for audit logging.
        """
        old_info = self.provider.get_key_info(key_id)
        new_info = self.provider.rotate_key(key_id)

        event = RotationEvent(
            key_id=key_id,
            old_version=old_info.key_version,
            new_version=new_info.key_version,
            rotated_at=datetime.now(timezone.utc),
            rotated_by=rotated_by,
            reason=reason,
        )
        self._rotation_history.append(event)
        logger.warning(
            "KEY ROTATION: key_id=%s %s → %s reason=%r by=%s",
            key_id, old_info.key_version, new_info.key_version, reason, rotated_by,
        )
        return event

    def rotation_history(self, key_id: Optional[str] = None) -> list[RotationEvent]:
        """Return rotation events, optionally filtered by key_id."""
        if key_id:
            return [e for e in self._rotation_history if e.key_id == key_id]
        return list(self._rotation_history)

    def needs_rotation(
        self,
        key_id: str,
        max_age_days: int = 90,
    ) -> bool:
        """
        Return True if the key is older than max_age_days.
        Callers should schedule rotation when this returns True.
        """
        info = self.provider.get_key_info(key_id)
        now = datetime.now(timezone.utc)
        created = info.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        return age_days >= max_age_days
