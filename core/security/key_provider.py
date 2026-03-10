"""
UAE v3 — Key Provider Abstraction

Defines the abstract interface for all key management backends.
Concrete implementations: LocalKeyProvider, EnvKeyProvider.
Future: AwsKmsKeyProvider, GcpKmsKeyProvider, VaultKeyProvider.

Design principles:
  - Private keys never leave the provider.
  - All signing happens inside the provider.
  - Consumers only see public keys and signatures.
  - Key versions are tracked for rotation support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class KeyInfo:
    """Metadata about a managed key."""
    key_id: str
    key_version: str
    algorithm: str          # "RSA-SHA256" | "Ed25519" | "ECDSA-P256"
    public_key_pem: str
    created_at: datetime
    expires_at: Optional[datetime]
    is_active: bool
    provider_type: str      # "local" | "env" | "hsm" | "kms"


class KeyProvider(ABC):
    """
    Abstract key provider interface.

    Every production deployment MUST configure a concrete provider.
    The LocalKeyProvider is safe for development only.
    The EnvKeyProvider reads keys from environment variables.
    Future providers connect to HSM/KMS infrastructure.
    """

    @abstractmethod
    def get_key_info(self, key_id: str) -> KeyInfo:
        """Return metadata for a key (no private key material)."""

    @abstractmethod
    def get_public_key_pem(self, key_id: str) -> str:
        """Return PEM-encoded public key for external verification."""

    @abstractmethod
    def sign(self, key_id: str, payload: bytes) -> bytes:
        """
        Sign payload with the named key.
        Returns raw signature bytes. Private key never leaves the provider.
        """

    @abstractmethod
    def list_active_keys(self) -> list[KeyInfo]:
        """Return all active keys managed by this provider."""

    @abstractmethod
    def rotate_key(self, key_id: str) -> KeyInfo:
        """
        Generate a new key version, retiring the current one.
        Old signatures remain verifiable via the old public key.
        Returns KeyInfo for the new key version.
        """

    def verify(self, key_id: str, payload: bytes, signature: bytes) -> bool:
        """
        Verify a signature using the named key's public key.
        Default implementation uses the public key — subclasses may override
        to delegate to HSM verification.
        """
        from core.security.signing_service import verify_with_public_key_pem
        pub_pem = self.get_public_key_pem(key_id)
        info = self.get_key_info(key_id)
        return verify_with_public_key_pem(pub_pem, payload, signature, info.algorithm)
