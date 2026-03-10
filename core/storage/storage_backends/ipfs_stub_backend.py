"""
UAE v3 — IPFS Stub Storage Backend

IMPORTANT: This is NOT a real IPFS implementation.
It is a correct storage abstraction that:
  1. Uses the same content-addressing semantics as IPFS (SHA-256 CIDs)
  2. Stores objects locally, mimicking the IPFS interface contract
  3. Can be swapped for a real IPFS client (ipfshttpclient) later

When to upgrade:
  - When you need true content-addressed distributed storage
  - When nodes need to share content without direct HTTP
  - Install: pip install ipfshttpclient
  - Then replace this class with IPFSStorageBackend(api_url="http://localhost:5001")

The interface is intentionally identical to FSStorageBackend.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from core.storage.content_addressing import compute_cid, verify_content
from core.storage.storage_backends.fs_backend import FSStorageBackend

logger = logging.getLogger(__name__)

_IPFS_API_URL = os.environ.get("UAE_IPFS_API_URL", "")


class IPFSStubBackend(FSStorageBackend):
    """
    IPFS stub that stores locally but uses IPFS-compatible CID semantics.

    If UAE_IPFS_API_URL is set, logs a notice that real IPFS is not connected.
    Future: replace with real ipfshttpclient integration.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(os.environ.get("UAE_STORAGE_DIR", "/tmp/uae_storage")) / "ipfs_stub"
        super().__init__(base_dir)

        if _IPFS_API_URL:
            logger.warning(
                "UAE_IPFS_API_URL is set (%s) but IPFSStubBackend does NOT connect to IPFS. "
                "Objects are stored locally. Upgrade to real IPFSStorageBackend for production.",
                _IPFS_API_URL,
            )
        else:
            logger.info(
                "IPFSStubBackend active (local storage, IPFS-compatible CIDs). "
                "Set UAE_IPFS_API_URL and upgrade to real IPFS for distributed storage."
            )

    def put(self, data: bytes, *, expected_cid: Optional[str] = None) -> str:
        cid = super().put(data, expected_cid=expected_cid)
        logger.debug("IPFSStub: stored object cid=%s (local, not pinned to IPFS)", cid)
        return cid

    def get(self, cid: str) -> bytes:
        return super().get(cid)

    def pin_status(self, cid: str) -> dict:
        """
        Stub: returns not-pinned status.
        Real IPFS backend would check ipfs.pin.ls().
        """
        return {
            "cid": cid,
            "pinned": False,
            "backend": "ipfs_stub",
            "note": "Real IPFS pinning not enabled. Upgrade to IPFSStorageBackend.",
        }
