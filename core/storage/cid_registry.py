"""
UAE v3 — CID Registry

Tracks content addresses (CIDs) for stored objects.
Enables deduplication: if content with the same CID already exists,
storage is skipped and the existing reference is returned.

In production: backed by the database (a cid_registry table).
For now: in-memory with optional persistence.

Used by:
  - SourceRegistry — register source CIDs
  - SourceBundle export/import — bundle CID tracking
  - Audit — reference content at a point in time
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.storage.content_addressing import is_valid_cid

logger = logging.getLogger(__name__)


@dataclass
class CIDEntry:
    """A registered CID entry."""
    cid: str
    object_type: str        # "source" | "bundle" | "claim_snapshot" | "audit"
    object_id: str          # internal ID (source_id, bundle_id, etc.)
    backend: str            # "local" | "ipfs_stub" | "s3"
    backend_ref: str        # path or remote reference
    created_at: datetime
    node_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class CIDRegistry:
    """
    In-memory CID registry with optional JSON persistence.

    Production upgrade path: replace with DB-backed async store.
    """

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._store: dict[str, CIDEntry] = {}  # cid -> entry
        self._by_object: dict[str, str] = {}   # object_id -> cid
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load()

    def register(
        self,
        cid: str,
        object_type: str,
        object_id: str,
        backend: str,
        backend_ref: str,
        *,
        node_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> CIDEntry:
        """Register a CID. Returns existing entry if CID already known."""
        if not is_valid_cid(cid):
            raise ValueError(f"Invalid CID format: {cid!r}")

        if cid in self._store:
            logger.debug("CID already registered: %s", cid)
            return self._store[cid]

        entry = CIDEntry(
            cid=cid,
            object_type=object_type,
            object_id=object_id,
            backend=backend,
            backend_ref=backend_ref,
            created_at=datetime.now(timezone.utc),
            node_id=node_id,
            metadata=metadata or {},
        )
        self._store[cid] = entry
        self._by_object[object_id] = cid
        if self._persist_path:
            self._save()
        logger.info("CID registered: %s (type=%s id=%s)", cid, object_type, object_id)
        return entry

    def lookup_by_cid(self, cid: str) -> Optional[CIDEntry]:
        return self._store.get(cid)

    def lookup_by_object(self, object_id: str) -> Optional[CIDEntry]:
        cid = self._by_object.get(object_id)
        return self._store.get(cid) if cid else None

    def exists(self, cid: str) -> bool:
        return cid in self._store

    def list_by_type(self, object_type: str) -> list[CIDEntry]:
        return [e for e in self._store.values() if e.object_type == object_type]

    def _save(self) -> None:
        data = {
            cid: {
                "cid": e.cid,
                "object_type": e.object_type,
                "object_id": e.object_id,
                "backend": e.backend,
                "backend_ref": e.backend_ref,
                "created_at": e.created_at.isoformat(),
                "node_id": e.node_id,
                "metadata": e.metadata,
            }
            for cid, e in self._store.items()
        }
        self._persist_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        data = json.loads(self._persist_path.read_text())
        for cid, d in data.items():
            entry = CIDEntry(
                cid=d["cid"],
                object_type=d["object_type"],
                object_id=d["object_id"],
                backend=d["backend"],
                backend_ref=d["backend_ref"],
                created_at=datetime.fromisoformat(d["created_at"]),
                node_id=d.get("node_id"),
                metadata=d.get("metadata", {}),
            )
            self._store[cid] = entry
            self._by_object[entry.object_id] = cid


# Module-level singleton
_registry: Optional[CIDRegistry] = None


def get_cid_registry() -> CIDRegistry:
    global _registry
    if _registry is None:
        _registry = CIDRegistry()
    return _registry
