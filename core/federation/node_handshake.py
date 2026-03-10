"""
UAE v3 — Node Handshake Protocol

Implements the trust bootstrap between two UAE nodes.
A handshake must succeed before any federation messages are exchanged.

Handshake flow:
  1. Node A sends HELLO with its node_id, public_key_pem, node_url, signed nonce
  2. Node B validates signature, registers Node A's public key
  3. Node B responds with its own HELLO (mutual authentication)
  4. Both nodes store each other's public keys for message verification

After a successful handshake:
  - Node A's public key is trusted by Node B for message verification
  - Node B's public key is trusted by Node A
  - No further handshakes needed until key rotation

Key rotation:
  - After rotating a node key, re-initiate handshake with all peers
  - Old public key remains valid for verifying historical messages
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.security.signing_service import (
    sign_with_private_key_pem,
    verify_with_public_key_pem,
)

logger = logging.getLogger(__name__)

HANDSHAKE_SCHEMA_VERSION = "uae-handshake-v1"


class HandshakeError(Exception):
    """Raised when a node handshake fails."""


def build_hello_payload(
    node_id: str,
    public_key_pem: str,
    node_url: str,
    private_key_pem: str,
    *,
    algorithm: str = "RSA-SHA256",
) -> dict:
    """
    Build a signed HELLO payload for initiating a handshake.

    The nonce prevents replay of the hello message itself.
    The signature proves possession of the private key corresponding to public_key_pem.
    """
    nonce = secrets.token_hex(16)
    timestamp = datetime.now(timezone.utc).isoformat()

    # The signed content is deterministic
    signed_content = json.dumps({
        "node_id": node_id,
        "nonce": nonce,
        "timestamp": timestamp,
        "schema_version": HANDSHAKE_SCHEMA_VERSION,
    }, sort_keys=True, separators=(",", ":"))

    import base64
    sig_bytes = sign_with_private_key_pem(
        private_key_pem, signed_content.encode("utf-8"), algorithm
    )
    signature = base64.b64encode(sig_bytes).decode("ascii")

    return {
        "schema_version": HANDSHAKE_SCHEMA_VERSION,
        "node_id": node_id,
        "public_key_pem": public_key_pem,
        "node_url": node_url,
        "nonce": nonce,
        "timestamp": timestamp,
        "algorithm": algorithm,
        "signature": signature,
    }


def verify_hello_payload(payload: dict) -> bool:
    """
    Verify a HELLO payload's signature.
    Returns True if the signature is valid.
    """
    import base64

    required_fields = {"node_id", "public_key_pem", "nonce", "timestamp", "signature"}
    if not required_fields.issubset(payload.keys()):
        logger.warning("HELLO payload missing required fields")
        return False

    signed_content = json.dumps({
        "node_id": payload["node_id"],
        "nonce": payload["nonce"],
        "timestamp": payload["timestamp"],
        "schema_version": payload.get("schema_version", HANDSHAKE_SCHEMA_VERSION),
    }, sort_keys=True, separators=(",", ":"))

    try:
        sig_bytes = base64.b64decode(payload["signature"])
    except Exception:
        logger.warning("Invalid base64 in HELLO signature from %s", payload.get("node_id"))
        return False

    return verify_with_public_key_pem(
        payload["public_key_pem"],
        signed_content.encode("utf-8"),
        sig_bytes,
        payload.get("algorithm", "RSA-SHA256"),
    )


class NodeHandshakeProtocol:
    """
    Manages the handshake state for a node.

    In-memory peer key store (keyed by node_id → public_key_pem).
    In production with multiple workers, this should be DB-backed.
    """

    def __init__(
        self,
        local_node_id: str,
        local_private_key_pem: str,
        local_public_key_pem: str,
        local_node_url: str,
    ) -> None:
        self.local_node_id = local_node_id
        self._private_key_pem = local_private_key_pem
        self.local_public_key_pem = local_public_key_pem
        self.local_node_url = local_node_url
        # Trusted peers: node_id -> {public_key_pem, algorithm, node_url, trusted_at}
        self._trusted_peers: dict[str, dict] = {}

    def build_hello(self, algorithm: str = "RSA-SHA256") -> dict:
        """Build this node's HELLO payload."""
        return build_hello_payload(
            self.local_node_id,
            self.local_public_key_pem,
            self.local_node_url,
            self._private_key_pem,
            algorithm=algorithm,
        )

    def receive_hello(self, hello: dict) -> bool:
        """
        Process a HELLO from a peer node.
        Returns True if accepted and peer is now trusted.
        """
        if not verify_hello_payload(hello):
            logger.error("HELLO verification failed from node %s", hello.get("node_id"))
            return False

        peer_id = hello["node_id"]
        self._trusted_peers[peer_id] = {
            "public_key_pem": hello["public_key_pem"],
            "algorithm": hello.get("algorithm", "RSA-SHA256"),
            "node_url": hello.get("node_url", ""),
            "trusted_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "Handshake accepted: local=%s peer=%s url=%s",
            self.local_node_id, peer_id, hello.get("node_url"),
        )
        return True

    def get_peer_public_key(self, node_id: str) -> Optional[str]:
        """Return trusted public key for a peer, or None if not handshaked."""
        peer = self._trusted_peers.get(node_id)
        return peer["public_key_pem"] if peer else None

    def is_peer_trusted(self, node_id: str) -> bool:
        return node_id in self._trusted_peers

    def list_trusted_peers(self) -> list[dict]:
        return [
            {"node_id": nid, **info}
            for nid, info in self._trusted_peers.items()
        ]
