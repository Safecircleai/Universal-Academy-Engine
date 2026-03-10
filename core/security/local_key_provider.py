"""
UAE v3 — Local Key Provider

Stores RSA key pairs on the local filesystem (or in memory for tests).
Safe for: development, single-node testing, CI.
NOT safe for: production multi-node deployments (use EnvKeyProvider or KMS).

Key storage layout (when file_based=True):
  {key_dir}/{key_id}/private.pem
  {key_dir}/{key_id}/public.pem
  {key_dir}/{key_id}/meta.json

SECURITY NOTE: In production, private keys must be protected by filesystem
permissions (chmod 600) and ideally stored in an encrypted volume.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.security.key_provider import KeyInfo, KeyProvider
from core.security.signing_service import sign_with_private_key_pem

logger = logging.getLogger(__name__)

_CRYPTO_AVAILABLE = False
try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
    from cryptography.hazmat.backends import default_backend
    _CRYPTO_AVAILABLE = True
except ImportError:
    pass


class LocalKeyProvider(KeyProvider):
    """
    File-system-backed RSA key provider for development and single-node use.

    Usage:
        provider = LocalKeyProvider(key_dir="/var/uae/keys")
        key_info = provider.create_key("node-signing-key")
        signature = provider.sign("node-signing-key", b"payload")
    """

    def __init__(
        self,
        key_dir: str | Path | None = None,
        algorithm: str = "RSA-SHA256",
    ) -> None:
        self.key_dir = Path(key_dir) if key_dir else None
        self.algorithm = algorithm
        # In-memory store for tests (key_id -> {private_pem, public_pem, info})
        self._memory_store: dict[str, dict] = {}

        if self.key_dir:
            self.key_dir.mkdir(parents=True, exist_ok=True)

    def create_key(
        self,
        key_id: str,
        *,
        expires_at: Optional[datetime] = None,
    ) -> KeyInfo:
        """Generate a new key pair and persist it."""
        priv_pem, pub_pem = self._generate_rsa_pair()
        version = "v1"
        info = KeyInfo(
            key_id=key_id,
            key_version=version,
            algorithm=self.algorithm,
            public_key_pem=pub_pem,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            is_active=True,
            provider_type="local",
        )
        self._store_key(key_id, priv_pem, pub_pem, info)
        logger.info("LocalKeyProvider: created key %s", key_id)
        return info

    # ------------------------------------------------------------------
    # KeyProvider interface
    # ------------------------------------------------------------------

    def get_key_info(self, key_id: str) -> KeyInfo:
        entry = self._load_key(key_id)
        if entry is None:
            raise KeyError(f"Key not found: {key_id!r}")
        return entry["info"]

    def get_public_key_pem(self, key_id: str) -> str:
        entry = self._load_key(key_id)
        if entry is None:
            raise KeyError(f"Key not found: {key_id!r}")
        return entry["public_pem"]

    def sign(self, key_id: str, payload: bytes) -> bytes:
        entry = self._load_key(key_id)
        if entry is None:
            raise KeyError(f"Key not found: {key_id!r}")
        return sign_with_private_key_pem(entry["private_pem"], payload, self.algorithm)

    def list_active_keys(self) -> list[KeyInfo]:
        keys = []
        if self.key_dir and self.key_dir.exists():
            for sub in self.key_dir.iterdir():
                if sub.is_dir():
                    entry = self._load_key(sub.name)
                    if entry and entry["info"].is_active:
                        keys.append(entry["info"])
        for key_id, entry in self._memory_store.items():
            if entry["info"].is_active:
                keys.append(entry["info"])
        return keys

    def rotate_key(self, key_id: str) -> KeyInfo:
        """Generate new version, mark old version inactive."""
        old = self._load_key(key_id)
        if old is None:
            raise KeyError(f"Key not found: {key_id!r}")

        # Archive old
        old_info = old["info"]
        archived_id = f"{key_id}__archived__{old_info.key_version}"
        self._store_key(archived_id, old["private_pem"], old["public_pem"], old_info)

        # Create new version
        priv_pem, pub_pem = self._generate_rsa_pair()
        parts = old_info.key_version.lstrip("v").split(".")
        new_version = f"v{int(parts[0]) + 1}"
        new_info = KeyInfo(
            key_id=key_id,
            key_version=new_version,
            algorithm=self.algorithm,
            public_key_pem=pub_pem,
            created_at=datetime.now(timezone.utc),
            expires_at=None,
            is_active=True,
            provider_type="local",
        )
        self._store_key(key_id, priv_pem, pub_pem, new_info)
        logger.info("LocalKeyProvider: rotated key %s → %s", key_id, new_version)
        return new_info

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_rsa_pair(self) -> tuple[str, str]:
        if not _CRYPTO_AVAILABLE:
            # Deterministic HMAC-based dev pair
            return "DUMMY_PRIVATE_KEY", "DUMMY_PUBLIC_KEY"

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
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

    def _store_key(self, key_id: str, priv_pem: str, pub_pem: str, info: KeyInfo) -> None:
        if self.key_dir:
            kd = self.key_dir / key_id
            kd.mkdir(parents=True, exist_ok=True)
            (kd / "private.pem").write_text(priv_pem)
            (kd / "public.pem").write_text(pub_pem)
            meta = {
                "key_id": info.key_id,
                "key_version": info.key_version,
                "algorithm": info.algorithm,
                "created_at": info.created_at.isoformat(),
                "expires_at": info.expires_at.isoformat() if info.expires_at else None,
                "is_active": info.is_active,
                "provider_type": info.provider_type,
            }
            (kd / "meta.json").write_text(json.dumps(meta, indent=2))
        else:
            self._memory_store[key_id] = {
                "private_pem": priv_pem,
                "public_pem": pub_pem,
                "info": info,
            }

    def _load_key(self, key_id: str) -> dict | None:
        if key_id in self._memory_store:
            return self._memory_store[key_id]
        if self.key_dir:
            kd = self.key_dir / key_id
            if not kd.exists():
                return None
            priv_pem = (kd / "private.pem").read_text()
            pub_pem = (kd / "public.pem").read_text()
            meta = json.loads((kd / "meta.json").read_text())
            info = KeyInfo(
                key_id=meta["key_id"],
                key_version=meta["key_version"],
                algorithm=meta["algorithm"],
                public_key_pem=pub_pem,
                created_at=datetime.fromisoformat(meta["created_at"]),
                expires_at=datetime.fromisoformat(meta["expires_at"]) if meta["expires_at"] else None,
                is_active=meta["is_active"],
                provider_type=meta["provider_type"],
            )
            return {"private_pem": priv_pem, "public_pem": pub_pem, "info": info}
        return None
