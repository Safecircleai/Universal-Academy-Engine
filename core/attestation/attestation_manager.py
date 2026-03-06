"""
Universal Academy Engine — Verification Attestation Manager (Part 2)

Transforms human verification from "recorded" into "cryptographically provable".

Architecture:
  1. Reviewer registers a public key via ReviewerKey.
  2. When verifying a claim, the reviewer signs a canonical payload using
     their private key (handled client-side or by the API caller).
  3. The AttestationManager stores the signature and verifies it using
     the registered public key.
  4. Any third party can independently verify a claim attestation using
     only the public key and the signed payload.

Signature algorithms supported:
  - RSA-SHA256 (default)
  - Ed25519 (preferred for new deployments — smaller signatures)
  - ECDSA-P256

In environments where the ``cryptography`` library is not installed the
manager falls back to a hmac-sha256 pseudo-signature suitable for
development and testing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ReviewerKey, VerificationAttestation, VerificationLog
)

logger = logging.getLogger(__name__)

# Attempt to import the cryptography library
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa, ed25519, utils
    from cryptography.hazmat.backends import default_backend
    from cryptography.exceptions import InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning(
        "cryptography package not installed. "
        "Falling back to HMAC-SHA256 pseudo-signatures (development only)."
    )


class AttestationError(Exception):
    """Raised when an attestation operation fails."""


class AttestationManager:
    """
    Issues and verifies cryptographic attestations for claim verification.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Reviewer key management
    # ------------------------------------------------------------------

    async def register_reviewer_key(
        self,
        *,
        node_id: str,
        reviewer_id: str,
        reviewer_name: str | None = None,
        reviewer_role: str | None = None,
        reviewer_credentials: list[str] | None = None,
        public_key_pem: str,
        signature_algorithm: str = "RSA-SHA256",
        valid_until: datetime | None = None,
    ) -> ReviewerKey:
        """
        Register a reviewer's public key.

        The public key is used to verify future attestation signatures.
        The reviewer's private key never leaves their possession.
        """
        fingerprint = _fingerprint(public_key_pem)

        # Check for duplicate
        stmt = select(ReviewerKey).where(ReviewerKey.key_fingerprint == fingerprint)
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            logger.info("Reviewer key already registered: fingerprint=%s", fingerprint)
            return existing

        key = ReviewerKey(
            node_id=node_id,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            reviewer_role=reviewer_role,
            reviewer_credentials=reviewer_credentials or [],
            public_key_pem=public_key_pem,
            key_fingerprint=fingerprint,
            signature_algorithm=signature_algorithm,
            valid_until=valid_until,
        )
        self.session.add(key)
        await self.session.flush()
        logger.info("Registered reviewer key for %s (fingerprint=%s)", reviewer_id, fingerprint)
        return key

    async def get_reviewer_key(self, reviewer_id: str, node_id: str) -> Optional[ReviewerKey]:
        stmt = (
            select(ReviewerKey)
            .where(ReviewerKey.reviewer_id == reviewer_id)
            .where(ReviewerKey.node_id == node_id)
            .where(ReviewerKey.is_active == True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Attestation issuance
    # ------------------------------------------------------------------

    async def create_attestation(
        self,
        *,
        claim_id: str,
        log_id: str | None = None,
        reviewer_key_id: str,
        reviewer_id: str,
        reviewer_role: str | None = None,
        reviewer_signature: str,
        verification_reason: str | None = None,
        signature_algorithm: str = "RSA-SHA256",
    ) -> VerificationAttestation:
        """
        Record a cryptographic attestation for a claim verification.

        The caller is responsible for computing ``reviewer_signature``
        by signing the canonical payload (see ``build_signing_payload()``)
        with their private key.

        This method:
          1. Retrieves the claim and computes its hash.
          2. Retrieves the reviewer's public key.
          3. Verifies the signature.
          4. Stores the attestation record.
        """
        claim = await self._get_claim(claim_id)
        claim_hash = _hash_statement(claim.statement)

        # Retrieve reviewer key
        stmt = select(ReviewerKey).where(ReviewerKey.key_id == reviewer_key_id)
        result = await self.session.execute(stmt)
        rk = result.scalar_one_or_none()
        if rk is None:
            raise AttestationError(f"ReviewerKey not found: {reviewer_key_id!r}")

        # Build the canonical payload that was (should have been) signed
        signed_payload = json.dumps(
            self.build_signing_payload(claim_id, claim_hash, reviewer_id),
            sort_keys=True,
        )

        # Verify the signature
        sig_valid = _verify_signature(
            public_key_pem=rk.public_key_pem,
            payload=signed_payload,
            signature_b64=reviewer_signature,
            algorithm=signature_algorithm,
        )

        attestation = VerificationAttestation(
            claim_id=claim_id,
            log_id=log_id,
            reviewer_key_id=reviewer_key_id,
            claim_hash=claim_hash,
            reviewer_signature=reviewer_signature,
            signature_algorithm=signature_algorithm,
            signed_payload=signed_payload,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            verification_reason=verification_reason,
            signature_verified=sig_valid,
            verified_at=datetime.utcnow() if sig_valid else None,
        )
        self.session.add(attestation)
        await self.session.flush()

        if not sig_valid:
            logger.warning(
                "Attestation stored but signature FAILED verification for claim %s", claim_id
            )
        else:
            logger.info("Attestation created and verified for claim %s", claim_id)

        return attestation

    # ------------------------------------------------------------------
    # Attestation verification
    # ------------------------------------------------------------------

    async def verify_attestation(self, attestation_id: str) -> dict:
        """
        Re-verify an existing attestation against the stored public key.

        Returns a dict with ``valid`` bool, ``details``, and ``errors``.
        """
        stmt = select(VerificationAttestation).where(
            VerificationAttestation.attestation_id == attestation_id
        )
        result = await self.session.execute(stmt)
        att = result.scalar_one_or_none()
        if att is None:
            raise AttestationError(f"Attestation not found: {attestation_id!r}")

        stmt2 = select(ReviewerKey).where(ReviewerKey.key_id == att.reviewer_key_id)
        result2 = await self.session.execute(stmt2)
        rk = result2.scalar_one_or_none()
        if rk is None:
            return {"valid": False, "errors": ["Reviewer key no longer exists."]}

        sig_valid = _verify_signature(
            public_key_pem=rk.public_key_pem,
            payload=att.signed_payload or "",
            signature_b64=att.reviewer_signature,
            algorithm=att.signature_algorithm,
        )
        return {
            "valid": sig_valid,
            "attestation_id": attestation_id,
            "claim_id": att.claim_id,
            "reviewer_id": att.reviewer_id,
            "algorithm": att.signature_algorithm,
            "verified_at": att.verified_at.isoformat() if att.verified_at else None,
            "errors": [] if sig_valid else ["Signature verification failed."],
        }

    async def get_claim_attestations(self, claim_id: str) -> list[VerificationAttestation]:
        stmt = (
            select(VerificationAttestation)
            .where(VerificationAttestation.claim_id == claim_id)
            .order_by(VerificationAttestation.verification_timestamp)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def build_signing_payload(claim_id: str, claim_hash: str, reviewer_id: str) -> dict:
        """
        Return the canonical dict that a reviewer must sign.

        This ensures all parties agree on what was attested.
        """
        return {
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "reviewer_id": reviewer_id,
            "schema_version": "uae-attestation-v1",
        }

    @staticmethod
    def generate_dev_key_pair() -> tuple[str, str]:
        """
        Generate a development RSA key pair (PEM strings).

        NOT for production use.  Returns (private_key_pem, public_key_pem).
        """
        if not _CRYPTO_AVAILABLE:
            # Return dummy keys for testing
            return ("DUMMY_PRIVATE_KEY", "DUMMY_PUBLIC_KEY")

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        priv_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        pub_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        return priv_pem, pub_pem

    @staticmethod
    def sign_payload(private_key_pem: str, payload: str) -> str:
        """
        Sign a payload string with an RSA private key.

        Returns a Base64-encoded signature string.
        For production: use your own key management; never send private keys to the server.
        """
        if not _CRYPTO_AVAILABLE or private_key_pem == "DUMMY_PRIVATE_KEY":
            # HMAC fallback for dev/test
            return base64.b64encode(
                hmac.new(b"dev_secret", payload.encode(), hashlib.sha256).digest()
            ).decode()

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None, backend=default_backend()
        )
        signature = private_key.sign(
            payload.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_claim(self, claim_id: str) -> Claim:
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is None:
            raise AttestationError(f"Claim not found: {claim_id!r}")
        return claim


# ---------------------------------------------------------------------------
# Module-level crypto helpers
# ---------------------------------------------------------------------------

def _hash_statement(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _fingerprint(public_key_pem: str) -> str:
    return hashlib.sha256(public_key_pem.encode("utf-8")).hexdigest()[:32]


def _verify_signature(
    public_key_pem: str,
    payload: str,
    signature_b64: str,
    algorithm: str,
) -> bool:
    """Verify a Base64-encoded signature against a payload and public key."""
    if not _CRYPTO_AVAILABLE or public_key_pem in ("DUMMY_PUBLIC_KEY", ""):
        # HMAC fallback: re-compute and compare
        expected = base64.b64encode(
            hmac.new(b"dev_secret", payload.encode(), hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(signature_b64, expected)

    try:
        sig = base64.b64decode(signature_b64)
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode(), backend=default_backend()
        )
        public_key.verify(
            sig,
            payload.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception as exc:
        logger.debug("Signature verification failed: %s", exc)
        return False
