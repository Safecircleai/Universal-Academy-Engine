"""
UAE v3 — Revocation Store

Tracks revoked credentials and signing keys.
In production this would be backed by a database table or external CRL.
For now: in-memory store with optional persistence to a JSON file.

Used by:
  - CredentialIssuer — check before accepting a credential
  - AttestationManager — check reviewer key before verifying
  - FederationTransport — reject messages from revoked node keys
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RevocationEntry:
    """A revoked credential or key record."""
    entity_id: str          # credential_id or key_id or node_id
    entity_type: str        # "credential" | "key" | "node"
    revoked_at: datetime
    revoked_by: str
    reason: str
    metadata: dict = field(default_factory=dict)


class RevocationStore:
    """
    Thread-safe in-memory revocation store with optional JSON persistence.

    Production upgrade path: replace _store with DB-backed async queries.
    """

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._store: dict[str, RevocationEntry] = {}
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load()

    def revoke(
        self,
        entity_id: str,
        entity_type: str,
        *,
        revoked_by: str,
        reason: str,
        metadata: Optional[dict] = None,
    ) -> RevocationEntry:
        entry = RevocationEntry(
            entity_id=entity_id,
            entity_type=entity_type,
            revoked_at=datetime.now(timezone.utc),
            revoked_by=revoked_by,
            reason=reason,
            metadata=metadata or {},
        )
        self._store[entity_id] = entry
        if self._persist_path:
            self._save()
        logger.warning("REVOKED %s %s: %s (by %s)", entity_type, entity_id, reason, revoked_by)
        return entry

    def is_revoked(self, entity_id: str) -> bool:
        return entity_id in self._store

    def get_entry(self, entity_id: str) -> Optional[RevocationEntry]:
        return self._store.get(entity_id)

    def list_revocations(self, entity_type: Optional[str] = None) -> list[RevocationEntry]:
        entries = list(self._store.values())
        if entity_type:
            entries = [e for e in entries if e.entity_type == entity_type]
        return sorted(entries, key=lambda e: e.revoked_at, reverse=True)

    def _save(self) -> None:
        data = {
            eid: {
                "entity_id": e.entity_id,
                "entity_type": e.entity_type,
                "revoked_at": e.revoked_at.isoformat(),
                "revoked_by": e.revoked_by,
                "reason": e.reason,
                "metadata": e.metadata,
            }
            for eid, e in self._store.items()
        }
        self._persist_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        data = json.loads(self._persist_path.read_text())
        for eid, d in data.items():
            self._store[eid] = RevocationEntry(
                entity_id=d["entity_id"],
                entity_type=d["entity_type"],
                revoked_at=datetime.fromisoformat(d["revoked_at"]),
                revoked_by=d["revoked_by"],
                reason=d["reason"],
                metadata=d.get("metadata", {}),
            )
