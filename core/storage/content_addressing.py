"""
UAE v3 — Content Addressing

Generates content addresses (CIDs) for source bundles and file objects.
CIDs are deterministic: same content always produces the same CID.

Format: sha256:<hex_digest>  (self-describing, no IPFS multihash encoding)
This is intentionally simpler than real IPFS CIDs to avoid the dependency.
The interface is designed to be compatible with future true IPFS integration.

Usage:
    cid = compute_cid(file_bytes)
    assert cid == compute_cid(file_bytes)  # deterministic
    verify_content(file_bytes, cid)        # raises on mismatch
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Union


class ContentAddressError(Exception):
    """Raised when content address verification fails."""


def compute_cid(data: Union[bytes, str]) -> str:
    """
    Compute a content identifier for the given data.
    Returns: "sha256:<64-char-hex>"
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def compute_file_cid(path: Union[str, Path]) -> str:
    """Compute CID for a file on disk."""
    path = Path(path)
    return compute_cid(path.read_bytes())


def verify_content(data: Union[bytes, str], expected_cid: str) -> None:
    """
    Verify data against an expected CID.
    Raises ContentAddressError if they don't match.
    """
    actual = compute_cid(data)
    if actual != expected_cid:
        raise ContentAddressError(
            f"Content address mismatch.\n"
            f"  Expected: {expected_cid}\n"
            f"  Actual:   {actual}"
        )


def verify_file(path: Union[str, Path], expected_cid: str) -> None:
    """Verify a file on disk against an expected CID."""
    data = Path(path).read_bytes()
    verify_content(data, expected_cid)


def is_valid_cid(cid: str) -> bool:
    """Return True if the string has the expected CID format."""
    if not cid.startswith("sha256:"):
        return False
    hex_part = cid[7:]
    return len(hex_part) == 64 and all(c in "0123456789abcdef" for c in hex_part)


def cid_from_dict(data: dict) -> str:
    """Compute CID from a dict (canonical JSON encoding)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return compute_cid(canonical.encode("utf-8"))
