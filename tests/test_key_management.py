"""
Tests for UAE v3 Key Management

Covers:
  - LocalKeyProvider: key creation, signing, verification
  - Key rotation: old key still verifies historical signatures
  - RevocationStore: revoke and check
  - SigningService: sign_payload_b64 / verify_payload_b64
"""

from __future__ import annotations

import pytest

from core.security.local_key_provider import LocalKeyProvider
from core.security.signing_service import (
    sign_payload_b64, verify_payload_b64, hash_string, hash_bytes
)
from core.security.revocation_store import RevocationStore
from core.security.key_rotation import KeyRotationService


class TestLocalKeyProvider:
    @pytest.fixture
    def provider(self):
        # Use in-memory store (no key_dir)
        return LocalKeyProvider(key_dir=None)

    def test_create_key(self, provider):
        info = provider.create_key("test-key")
        assert info.key_id == "test-key"
        assert info.is_active
        assert info.provider_type == "local"

    def test_get_public_key(self, provider):
        provider.create_key("test-key-2")
        pub = provider.get_public_key_pem("test-key-2")
        assert pub  # not empty

    def test_sign_and_verify(self, provider):
        provider.create_key("signing-key")
        payload = b"hello world payload"
        sig = provider.sign("signing-key", payload)
        assert sig  # not empty bytes
        assert provider.verify("signing-key", payload, sig)

    def test_wrong_payload_fails_verify(self, provider):
        provider.create_key("verify-key")
        payload = b"original payload"
        sig = provider.sign("verify-key", payload)
        assert not provider.verify("verify-key", b"tampered payload", sig)

    def test_key_not_found_raises(self, provider):
        with pytest.raises(KeyError):
            provider.get_key_info("nonexistent")

    def test_list_active_keys(self, provider):
        provider.create_key("key-1")
        provider.create_key("key-2")
        active = provider.list_active_keys()
        ids = [k.key_id for k in active]
        assert "key-1" in ids
        assert "key-2" in ids


class TestKeyRotation:
    @pytest.fixture
    def provider(self):
        return LocalKeyProvider(key_dir=None)

    def test_rotate_creates_new_version(self, provider):
        info_v1 = provider.create_key("rotate-key")
        assert info_v1.key_version == "v1"
        rotation = KeyRotationService(provider)
        event = rotation.rotate("rotate-key", reason="test rotation")
        assert event.old_version == "v1"
        assert event.new_version == "v2"

    def test_rotation_history(self, provider):
        provider.create_key("hist-key")
        svc = KeyRotationService(provider)
        svc.rotate("hist-key")
        history = svc.rotation_history("hist-key")
        assert len(history) == 1
        assert history[0].key_id == "hist-key"

    def test_needs_rotation_fresh_key(self, provider):
        provider.create_key("fresh-key")
        svc = KeyRotationService(provider)
        assert not svc.needs_rotation("fresh-key", max_age_days=90)

    def test_needs_rotation_old_key(self, provider):
        from datetime import datetime, timedelta, timezone
        provider.create_key("old-key")
        # Manually age the key
        entry = provider._memory_store["old-key"]
        entry["info"].created_at = datetime.now(timezone.utc) - timedelta(days=100)
        svc = KeyRotationService(provider)
        assert svc.needs_rotation("old-key", max_age_days=90)


class TestRevocationStore:
    @pytest.fixture
    def store(self):
        return RevocationStore()

    def test_revoke_and_check(self, store):
        store.revoke("cred-123", "credential", revoked_by="admin", reason="test revocation")
        assert store.is_revoked("cred-123")

    def test_not_revoked(self, store):
        assert not store.is_revoked("not-revoked-id")

    def test_get_entry(self, store):
        store.revoke("key-456", "key", revoked_by="system", reason="compromised")
        entry = store.get_entry("key-456")
        assert entry is not None
        assert entry.entity_type == "key"
        assert entry.reason == "compromised"

    def test_list_by_type(self, store):
        store.revoke("c1", "credential", revoked_by="admin", reason="r1")
        store.revoke("k1", "key", revoked_by="system", reason="r2")
        store.revoke("c2", "credential", revoked_by="admin", reason="r3")
        creds = store.list_revocations("credential")
        assert len(creds) == 2
        keys = store.list_revocations("key")
        assert len(keys) == 1


class TestSigningService:
    def test_hash_string_deterministic(self):
        h1 = hash_string("test content")
        h2 = hash_string("test content")
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_bytes_deterministic(self):
        h = hash_bytes(b"binary content")
        assert len(h) == 64

    def test_sign_and_verify_payload(self):
        provider = LocalKeyProvider(key_dir=None)
        provider.create_key("payload-key")
        priv_pem = provider._memory_store["payload-key"]["private_pem"]
        pub_pem = provider._memory_store["payload-key"]["public_pem"]

        payload = {"claim_id": "c1", "action": "verify", "timestamp": "2026-01-01T00:00:00"}
        sig = sign_payload_b64(priv_pem, payload)
        assert verify_payload_b64(pub_pem, payload, sig)

    def test_tampered_payload_fails(self):
        provider = LocalKeyProvider(key_dir=None)
        provider.create_key("tamper-key")
        priv_pem = provider._memory_store["tamper-key"]["private_pem"]
        pub_pem = provider._memory_store["tamper-key"]["public_pem"]

        original = {"value": "original"}
        sig = sign_payload_b64(priv_pem, original)
        tampered = {"value": "tampered"}
        assert not verify_payload_b64(pub_pem, tampered, sig)
