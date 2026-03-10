"""
UAE v3 — Signing Service

Centralised signing and verification logic used by:
  - federation message signing
  - credential issuance
  - attestation generation
  - audit record signing

All operations route through the active KeyProvider — never bypass this
module with raw key material in application code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Attempt to import the cryptography library
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, ec, ed25519
    from cryptography.hazmat.backends import default_backend
    from cryptography.exceptions import InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning(
        "cryptography library not available — using HMAC-SHA256 fallback. "
        "NOT suitable for production."
    )


class SigningError(Exception):
    """Raised when signing or verification fails."""


def sign_with_private_key_pem(
    private_key_pem: str,
    payload: bytes,
    algorithm: str = "RSA-SHA256",
) -> bytes:
    """
    Sign payload bytes with a PEM-encoded private key.
    Returns raw signature bytes.

    Used internally by LocalKeyProvider. EnvKeyProvider and KMS providers
    override this via their own signing paths.
    """
    if not _CRYPTO_AVAILABLE or private_key_pem.startswith("DUMMY"):
        # HMAC-SHA256 fallback for dev/test
        return hmac.new(b"dev_secret_key", payload, hashlib.sha256).digest()

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem,
        password=None,
        backend=default_backend(),
    )

    if algorithm in ("RSA-SHA256", "RSA"):
        return private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    elif algorithm in ("Ed25519",):
        return private_key.sign(payload)
    elif algorithm in ("ECDSA-P256", "ECDSA"):
        return private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    else:
        raise SigningError(f"Unsupported algorithm: {algorithm}")


def verify_with_public_key_pem(
    public_key_pem: str,
    payload: bytes,
    signature: bytes,
    algorithm: str = "RSA-SHA256",
) -> bool:
    """
    Verify a raw signature against a PEM-encoded public key.
    Returns True if valid, False otherwise.
    """
    if not _CRYPTO_AVAILABLE or public_key_pem.startswith("DUMMY"):
        expected = hmac.new(b"dev_secret_key", payload, hashlib.sha256).digest()
        return hmac.compare_digest(signature, expected)

    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem,
            backend=default_backend(),
        )
        if algorithm in ("RSA-SHA256", "RSA"):
            public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
        elif algorithm in ("Ed25519",):
            public_key.verify(signature, payload)
        elif algorithm in ("ECDSA-P256", "ECDSA"):
            public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        else:
            raise SigningError(f"Unsupported algorithm: {algorithm}")
        return True
    except (InvalidSignature, Exception) as exc:
        logger.debug("Signature verification failed: %s", exc)
        return False


def sign_payload_b64(
    private_key_pem: str,
    payload_dict: dict[str, Any],
    algorithm: str = "RSA-SHA256",
) -> str:
    """
    Canonical JSON-encode a dict, sign it, return Base64 signature.
    Used for federation messages and attestations.
    """
    canonical = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    raw_sig = sign_with_private_key_pem(private_key_pem, canonical, algorithm)
    return base64.b64encode(raw_sig).decode("ascii")


def verify_payload_b64(
    public_key_pem: str,
    payload_dict: dict[str, Any],
    signature_b64: str,
    algorithm: str = "RSA-SHA256",
) -> bool:
    """
    Verify a Base64 signature against a canonically JSON-encoded dict.
    """
    try:
        canonical = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        raw_sig = base64.b64decode(signature_b64)
        return verify_with_public_key_pem(public_key_pem, canonical, raw_sig, algorithm)
    except Exception as exc:
        logger.debug("Payload verification error: %s", exc)
        return False


def hash_bytes(data: bytes) -> str:
    """Return SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_string(s: str) -> str:
    """Return SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical_timestamp() -> str:
    """UTC ISO-8601 timestamp for signing payloads."""
    return datetime.now(timezone.utc).isoformat()
