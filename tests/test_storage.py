"""
Tests for UAE v3 Content-Addressed Storage

Covers:
  - CID computation and verification
  - Source bundle export/import/verify
  - FSStorageBackend put/get/dedup
  - CIDRegistry register/lookup
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.storage.content_addressing import (
    compute_cid, verify_content, is_valid_cid, cid_from_dict, ContentAddressError
)
from core.storage.source_bundle import (
    export_source_bundle, verify_source_bundle, bundle_to_bytes, bundle_from_bytes
)
from core.storage.storage_backends.fs_backend import FSStorageBackend, FSBackendError
from core.storage.cid_registry import CIDRegistry


# ------------------------------------------------------------------
# Content Addressing
# ------------------------------------------------------------------

class TestContentAddressing:
    def test_cid_format(self):
        cid = compute_cid(b"hello")
        assert cid.startswith("sha256:")
        assert len(cid) == 7 + 64

    def test_deterministic(self):
        assert compute_cid(b"same data") == compute_cid(b"same data")

    def test_different_content_different_cid(self):
        assert compute_cid(b"a") != compute_cid(b"b")

    def test_string_input(self):
        cid = compute_cid("hello text")
        assert is_valid_cid(cid)

    def test_verify_correct_content(self):
        data = b"verify me"
        cid = compute_cid(data)
        verify_content(data, cid)  # should not raise

    def test_verify_tampered_raises(self):
        data = b"original"
        cid = compute_cid(data)
        with pytest.raises(ContentAddressError):
            verify_content(b"tampered", cid)

    def test_is_valid_cid_true(self):
        cid = compute_cid(b"data")
        assert is_valid_cid(cid)

    def test_is_valid_cid_false(self):
        assert not is_valid_cid("not-a-cid")
        assert not is_valid_cid("sha256:tooshort")
        assert not is_valid_cid("md5:abc123")

    def test_cid_from_dict_deterministic(self):
        d = {"key": "value", "number": 42}
        c1 = cid_from_dict(d)
        c2 = cid_from_dict(d)
        assert c1 == c2

    def test_cid_from_dict_order_independent(self):
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert cid_from_dict(d1) == cid_from_dict(d2)


# ------------------------------------------------------------------
# Source Bundle
# ------------------------------------------------------------------

class TestSourceBundle:
    @pytest.fixture
    def sample_bundle_data(self):
        source_meta = {
            "source_id": "src-001",
            "title": "Test Source",
            "publisher": "Test Publisher",
            "trust_tier": "TIER1",
        }
        texts = [
            {"text_id": "t1", "content": "First text block", "page_number": 1}
        ]
        claims = [
            {"claim_id": "c1", "statement": "Test claim", "claim_hash": "abc123"}
        ]
        return source_meta, texts, claims

    def test_export_bundle(self, sample_bundle_data):
        source, texts, claims = sample_bundle_data
        bundle = export_source_bundle(source, texts, claims)
        assert bundle["schema_version"] == "uae-bundle-v1"
        assert "manifest" in bundle
        assert "bundle_cid" in bundle["manifest"]

    def test_verify_valid_bundle(self, sample_bundle_data):
        source, texts, claims = sample_bundle_data
        bundle = export_source_bundle(source, texts, claims)
        result = verify_source_bundle(bundle)
        assert result["valid"], result["errors"]

    def test_verify_tampered_bundle(self, sample_bundle_data):
        source, texts, claims = sample_bundle_data
        bundle = export_source_bundle(source, texts, claims)
        # Tamper with a claim
        bundle["claims"][0]["statement"] = "TAMPERED"
        result = verify_source_bundle(bundle)
        assert not result["valid"]
        assert any("Claims CID" in e for e in result["errors"])

    def test_bundle_serialization(self, sample_bundle_data):
        source, texts, claims = sample_bundle_data
        bundle = export_source_bundle(source, texts, claims)
        data = bundle_to_bytes(bundle)
        recovered = bundle_from_bytes(data)
        assert recovered["bundle_id"] == bundle["bundle_id"]
        result = verify_source_bundle(recovered)
        assert result["valid"]

    def test_bundle_cid_tampered(self, sample_bundle_data):
        source, texts, claims = sample_bundle_data
        bundle = export_source_bundle(source, texts, claims)
        # Modify source without updating CIDs
        bundle["source"]["title"] = "TAMPERED TITLE"
        result = verify_source_bundle(bundle)
        assert not result["valid"]


# ------------------------------------------------------------------
# FSStorageBackend
# ------------------------------------------------------------------

class TestFSStorageBackend:
    @pytest.fixture
    def backend(self, tmp_path):
        return FSStorageBackend(tmp_path / "objects")

    def test_put_and_get(self, backend):
        data = b"test binary content"
        cid = backend.put(data)
        assert is_valid_cid(cid)
        retrieved = backend.get(cid)
        assert retrieved == data

    def test_dedup(self, backend):
        data = b"same content"
        cid1 = backend.put(data)
        cid2 = backend.put(data)
        assert cid1 == cid2

    def test_exists(self, backend):
        data = b"exist check"
        cid = backend.put(data)
        assert backend.exists(cid)
        assert not backend.exists("sha256:" + "0" * 64)

    def test_get_not_found(self, backend):
        with pytest.raises(FSBackendError):
            backend.get("sha256:" + "a" * 64)

    def test_delete(self, backend):
        data = b"delete me"
        cid = backend.put(data)
        assert backend.exists(cid)
        backend.delete(cid)
        assert not backend.exists(cid)

    def test_stat(self, backend):
        backend.put(b"obj1")
        backend.put(b"obj2")
        s = backend.stat()
        assert s["object_count"] == 2

    def test_expected_cid_mismatch(self, backend):
        from core.storage.storage_backends.fs_backend import FSBackendError
        with pytest.raises(FSBackendError):
            backend.put(b"data", expected_cid="sha256:" + "a" * 64)


# ------------------------------------------------------------------
# CIDRegistry
# ------------------------------------------------------------------

class TestCIDRegistry:
    @pytest.fixture
    def registry(self):
        return CIDRegistry()

    def test_register_and_lookup(self, registry):
        cid = compute_cid(b"test object")
        entry = registry.register(cid, "source", "src-001", "local", "/path/to/file")
        assert entry.cid == cid
        found = registry.lookup_by_cid(cid)
        assert found is not None
        assert found.object_id == "src-001"

    def test_lookup_by_object(self, registry):
        cid = compute_cid(b"object data")
        registry.register(cid, "bundle", "bundle-001", "local", "/path")
        found = registry.lookup_by_object("bundle-001")
        assert found is not None
        assert found.cid == cid

    def test_exists(self, registry):
        cid = compute_cid(b"exists check")
        assert not registry.exists(cid)
        registry.register(cid, "audit", "audit-001", "local", "/path")
        assert registry.exists(cid)

    def test_dedup_returns_existing(self, registry):
        cid = compute_cid(b"dedup test")
        e1 = registry.register(cid, "source", "src-a", "local", "/a")
        e2 = registry.register(cid, "source", "src-b", "local", "/b")
        assert e1.object_id == e2.object_id  # returns first registered

    def test_invalid_cid_raises(self, registry):
        with pytest.raises(ValueError):
            registry.register("invalid-cid", "source", "src-x", "local", "/path")

    def test_list_by_type(self, registry):
        cid1 = compute_cid(b"source1")
        cid2 = compute_cid(b"source2")
        cid3 = compute_cid(b"audit1")
        registry.register(cid1, "source", "s1", "local", "/s1")
        registry.register(cid2, "source", "s2", "local", "/s2")
        registry.register(cid3, "audit", "a1", "local", "/a1")
        sources = registry.list_by_type("source")
        assert len(sources) == 2
