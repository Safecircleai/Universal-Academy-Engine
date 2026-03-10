"""
UAE v3 — Federation Message Signing

All inter-node federation messages MUST be signed.
Unsigned messages are rejected by the transport server.

Message envelope:
  {
    "header": {
      "message_id":   "<uuid>",
      "message_type": "<type>",
      "sender_node_id": "<node_id>",
      "recipient_node_id": "<node_id>" | null,
      "timestamp":    "<ISO-8601 UTC>",
      "nonce":        "<hex-32>",
      "schema_version": "uae-federation-v3"
    },
    "body": { ... },
    "signature": "<base64>"   # signs canonical JSON of header + body
  }

The signature covers header + body to prevent:
  - Message tampering
  - Replay attacks (nonce + timestamp checked by replay_protection.py)
  - Sender impersonation (verified against registered node public key)
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.security.signing_service import (
    sign_with_private_key_pem,
    verify_with_public_key_pem,
    hash_string,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "uae-federation-v3"


class MessageSigningError(Exception):
    """Raised when message signing or verification fails."""


def build_message(
    message_type: str,
    sender_node_id: str,
    body: dict[str, Any],
    *,
    recipient_node_id: Optional[str] = None,
) -> dict:
    """
    Build an unsigned federation message envelope.
    Call sign_message() to attach the signature.
    """
    return {
        "header": {
            "message_id": str(uuid.uuid4()),
            "message_type": message_type,
            "sender_node_id": sender_node_id,
            "recipient_node_id": recipient_node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nonce": secrets.token_hex(16),
            "schema_version": SCHEMA_VERSION,
        },
        "body": body,
        "signature": None,
    }


def sign_message(
    message: dict,
    private_key_pem: str,
    algorithm: str = "RSA-SHA256",
) -> dict:
    """
    Sign a message envelope in-place. Returns the message with signature attached.
    The signature covers the canonical JSON of header + body.
    """
    signing_payload = _canonical_signing_payload(message)
    sig_bytes = sign_with_private_key_pem(
        private_key_pem, signing_payload.encode("utf-8"), algorithm
    )
    message = dict(message)
    message["signature"] = base64.b64encode(sig_bytes).decode("ascii")
    return message


def verify_message_signature(
    message: dict,
    public_key_pem: str,
    algorithm: str = "RSA-SHA256",
) -> bool:
    """
    Verify a signed federation message.
    Returns True if valid, False otherwise.
    """
    if not message.get("signature"):
        logger.warning("Federation message missing signature from %s",
                       message.get("header", {}).get("sender_node_id"))
        return False

    try:
        sig_bytes = base64.b64decode(message["signature"])
    except Exception:
        return False

    signing_payload = _canonical_signing_payload(message)
    return verify_with_public_key_pem(
        public_key_pem,
        signing_payload.encode("utf-8"),
        sig_bytes,
        algorithm,
    )


def message_digest(message: dict) -> str:
    """
    Return SHA-256 hex digest of the message (header + body).
    Used for deduplication and replay protection.
    """
    return hash_string(_canonical_signing_payload(message))


def _canonical_signing_payload(message: dict) -> str:
    """
    Canonical JSON string covering header + body (not the signature field).
    Must be deterministic: sorted keys, no extra whitespace.
    """
    payload = {
        "header": message["header"],
        "body": message["body"],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
