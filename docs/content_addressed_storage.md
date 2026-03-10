# UAE v3 — Content-Addressed Storage

## Overview

UAE v3 introduces content-addressed storage (CAS) for source documents and bundles.
Content identifiers (CIDs) are SHA-256 based and self-describing:

```
sha256:<64-hex-chars>
```

Same content always produces the same CID. This enables:
- **Deduplication**: identical documents are stored once
- **Integrity**: any tampering changes the CID
- **Portability**: bundles can be verified on any node without trusting the sender

## CID Format

```
sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

This is intentionally simpler than IPFS multihash. The interface is compatible
with future IPFS integration.

## Source Bundles

A source bundle packages a source document and its claims for cross-node sharing.

### Exporting

```python
from core.storage.source_bundle import export_source_bundle, bundle_to_bytes

bundle = export_source_bundle(
    source_meta={"source_id": "src-001", "title": "...", "trust_tier": "TIER1"},
    extracted_texts=[{"content": "...", "page_number": 1}],
    claims=[{"claim_id": "c1", "statement": "...", "claim_hash": "..."}],
)
data = bundle_to_bytes(bundle)
```

### Importing and Verifying

```python
from core.storage.source_bundle import bundle_from_bytes, verify_source_bundle

bundle = bundle_from_bytes(data)
result = verify_source_bundle(bundle)
if not result["valid"]:
    raise Exception(f"Bundle tampered: {result['errors']}")
```

## Storage Backends

### FSStorageBackend (Local)

Production-suitable for single-node deployments.

```python
from core.storage.storage_backends.fs_backend import FSStorageBackend

backend = FSStorageBackend("/var/uae/storage")
cid = backend.put(file_bytes)
data = backend.get(cid)
```

Objects are stored at: `{base_dir}/{cid[:4]}/{cid[7:]}.bin`

### IPFSStubBackend

Same interface as FSStorageBackend. Stores locally with IPFS-compatible semantics.
Does NOT connect to real IPFS. Set `UAE_IPFS_API_URL` and upgrade to a real
IPFS client (`ipfshttpclient`) for distributed storage.

## CID Registry

Tracks all registered content addresses:

```python
from core.storage.cid_registry import get_cid_registry

registry = get_cid_registry()
entry = registry.register(cid, "source", "src-001", "local", "/path/to/file")
found = registry.lookup_by_object("src-001")
```

## Upgrade Path to Real IPFS

1. Install: `pip install ipfshttpclient`
2. Run an IPFS daemon: `ipfs daemon`
3. Replace `IPFSStubBackend` with a `IPFSStorageBackend` subclass that calls
   `ipfshttpclient.connect().add_bytes()` and `ipfshttpclient.connect().cat()`
4. CID format will change from `sha256:...` to IPFS multihash format
   (update the registry accordingly)

The `KeyProvider` abstraction and bundle contract remain unchanged.
