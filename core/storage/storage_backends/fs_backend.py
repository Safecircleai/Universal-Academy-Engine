"""
UAE v3 — Filesystem Storage Backend

Stores content-addressed objects on the local filesystem.
Objects are stored at: {base_dir}/{cid_prefix}/{cid}.bin

The directory is split on the first 4 hex chars of the SHA-256 digest to
avoid filesystem limits on large directories (same approach as git object store).

This backend is production-suitable for single-node deployments.
For multi-node deployments, use a shared volume or upgrade to S3.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from core.storage.content_addressing import compute_cid, verify_content

logger = logging.getLogger(__name__)


class FSBackendError(Exception):
    """Raised when a filesystem storage operation fails."""


class FSStorageBackend:
    """
    Local filesystem content-addressed object store.

    Objects are immutable once written (same CID = same content).
    Existing objects are never overwritten.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("FSStorageBackend: base_dir=%s", self.base_dir)

    def put(self, data: bytes, *, expected_cid: Optional[str] = None) -> str:
        """
        Store bytes. Returns the CID.
        If expected_cid is given, verifies before storing.
        If the object already exists, returns existing CID (dedup).
        """
        cid = compute_cid(data)
        if expected_cid and cid != expected_cid:
            raise FSBackendError(
                f"CID mismatch: expected {expected_cid}, computed {cid}"
            )

        path = self._cid_to_path(cid)
        if path.exists():
            logger.debug("FSBackend: object already exists: %s", cid)
            return cid

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.debug("FSBackend: stored %d bytes at cid=%s", len(data), cid)
        return cid

    def get(self, cid: str) -> bytes:
        """Retrieve bytes by CID. Raises FSBackendError if not found."""
        path = self._cid_to_path(cid)
        if not path.exists():
            raise FSBackendError(f"Object not found: {cid}")
        data = path.read_bytes()
        verify_content(data, cid)
        return data

    def exists(self, cid: str) -> bool:
        return self._cid_to_path(cid).exists()

    def delete(self, cid: str) -> bool:
        """Delete an object. Returns True if deleted, False if not found."""
        path = self._cid_to_path(cid)
        if path.exists():
            path.unlink()
            logger.info("FSBackend: deleted %s", cid)
            return True
        return False

    def list_cids(self) -> list[str]:
        """List all stored CIDs."""
        cids = []
        for prefix_dir in self.base_dir.iterdir():
            if prefix_dir.is_dir():
                for obj_file in prefix_dir.iterdir():
                    if obj_file.is_file():
                        cids.append(f"sha256:{obj_file.stem}")
        return sorted(cids)

    def stat(self) -> dict:
        """Return storage statistics."""
        total_bytes = 0
        count = 0
        for prefix_dir in self.base_dir.iterdir():
            if prefix_dir.is_dir():
                for obj_file in prefix_dir.iterdir():
                    if obj_file.is_file():
                        count += 1
                        total_bytes += obj_file.stat().st_size
        return {"object_count": count, "total_bytes": total_bytes, "base_dir": str(self.base_dir)}

    def _cid_to_path(self, cid: str) -> Path:
        """Map CID to filesystem path using 4-char prefix sharding."""
        # cid format: "sha256:<64-hex>"
        hex_part = cid.replace("sha256:", "")
        prefix = hex_part[:4]
        return self.base_dir / prefix / f"{hex_part}.bin"
