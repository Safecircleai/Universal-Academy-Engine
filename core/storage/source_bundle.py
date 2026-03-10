"""
UAE v3 — Source Bundle

A source bundle is a portable, integrity-verified package containing:
  - Source metadata (title, publisher, trust_tier, etc.)
  - Extracted text blocks
  - Claim references (with hashes)
  - A manifest with CIDs for all components

Bundles can be:
  - Exported from a node and shared with peers
  - Imported and verified against the manifest
  - Attached to FederatedClaimRecords for full provenance

Bundle structure (JSON):
  {
    "bundle_id": "<uuid>",
    "schema_version": "uae-bundle-v1",
    "created_at": "<ISO-8601>",
    "source": { ...source metadata... },
    "extracted_texts": [ {...}, ... ],
    "claims": [ { "claim_id": ..., "claim_hash": ..., "statement": ... }, ... ],
    "manifest": {
      "source_cid": "sha256:...",
      "texts_cid": "sha256:...",
      "claims_cid": "sha256:...",
      "bundle_cid": "sha256:..."  # hash of the whole bundle (excluding bundle_cid itself)
    }
  }
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.storage.content_addressing import compute_cid, verify_content, cid_from_dict


BUNDLE_SCHEMA_VERSION = "uae-bundle-v1"


class BundleError(Exception):
    """Raised when bundle creation or verification fails."""


def export_source_bundle(
    source_meta: dict[str, Any],
    extracted_texts: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Export a source and its claims as a portable, integrity-verified bundle.

    source_meta — serialisable source record (no SQLAlchemy objects)
    extracted_texts — list of text block dicts
    claims — list of claim dicts (must include claim_hash)
    """
    bundle_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Compute per-section CIDs
    source_cid = cid_from_dict(source_meta)
    texts_cid = compute_cid(json.dumps(extracted_texts, sort_keys=True, separators=(",", ":")))
    claims_cid = compute_cid(json.dumps(claims, sort_keys=True, separators=(",", ":")))

    # Build bundle without bundle_cid first
    bundle = {
        "bundle_id": bundle_id,
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": now,
        "source": source_meta,
        "extracted_texts": extracted_texts,
        "claims": claims,
        "manifest": {
            "source_cid": source_cid,
            "texts_cid": texts_cid,
            "claims_cid": claims_cid,
        },
    }

    # bundle_cid signs the whole bundle content (excluding itself)
    bundle_cid = cid_from_dict(bundle)
    bundle["manifest"]["bundle_cid"] = bundle_cid

    return bundle


def verify_source_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """
    Verify a bundle's integrity.
    Returns dict with keys: valid (bool), errors (list[str]).
    """
    errors = []

    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        errors.append(
            f"Unsupported schema_version: {bundle.get('schema_version')!r}"
        )

    manifest = bundle.get("manifest", {})

    # Verify source CID
    if "source" in bundle and "source_cid" in manifest:
        actual = cid_from_dict(bundle["source"])
        if actual != manifest["source_cid"]:
            errors.append(f"Source CID mismatch: expected {manifest['source_cid']}, got {actual}")

    # Verify texts CID
    if "extracted_texts" in bundle and "texts_cid" in manifest:
        actual = compute_cid(
            json.dumps(bundle["extracted_texts"], sort_keys=True, separators=(",", ":"))
        )
        if actual != manifest["texts_cid"]:
            errors.append(f"Texts CID mismatch: expected {manifest['texts_cid']}, got {actual}")

    # Verify claims CID
    if "claims" in bundle and "claims_cid" in manifest:
        actual = compute_cid(
            json.dumps(bundle["claims"], sort_keys=True, separators=(",", ":"))
        )
        if actual != manifest["claims_cid"]:
            errors.append(f"Claims CID mismatch: expected {manifest['claims_cid']}, got {actual}")

    # Verify bundle CID (whole bundle integrity)
    if "bundle_cid" in manifest:
        stored_bundle_cid = manifest["bundle_cid"]
        # Recompute without bundle_cid in manifest
        check_bundle = dict(bundle)
        check_manifest = dict(manifest)
        del check_manifest["bundle_cid"]
        check_bundle["manifest"] = check_manifest
        actual_bundle_cid = cid_from_dict(check_bundle)
        if actual_bundle_cid != stored_bundle_cid:
            errors.append(
                f"Bundle CID mismatch (tampered?): "
                f"expected {stored_bundle_cid}, got {actual_bundle_cid}"
            )

    return {"valid": len(errors) == 0, "errors": errors}


def bundle_to_bytes(bundle: dict[str, Any]) -> bytes:
    """Serialise bundle to JSON bytes for transport or storage."""
    return json.dumps(bundle, sort_keys=True, indent=2).encode("utf-8")


def bundle_from_bytes(data: bytes) -> dict[str, Any]:
    """Deserialise bundle from JSON bytes."""
    return json.loads(data.decode("utf-8"))
