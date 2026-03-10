# UAE v3 — Key Management

## Architecture

UAE v3 uses a pluggable `KeyProvider` abstraction. Private keys never leave the provider.
All signing happens inside the provider; consumers only receive signatures and public keys.

## Providers

### LocalKeyProvider (Dev / Single-Node)

Stores RSA key pairs on the local filesystem.

```python
from core.security.local_key_provider import LocalKeyProvider

provider = LocalKeyProvider(key_dir="/var/uae/keys")
info = provider.create_key("node-signing-key")
signature = provider.sign("node-signing-key", b"payload")
```

**Safe for**: development, CI, single-node production with encrypted filesystem
**Not safe for**: multi-process without shared filesystem, production without key protection

Key storage: `{key_dir}/{key_id}/private.pem` (chmod 600 required in production)

### EnvKeyProvider (Containerised Production)

Reads key material from environment variables. Suitable for Docker/Kubernetes.

```bash
UAE_NODE_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
UAE_NODE_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n..."
UAE_NODE_KEY_ALGORITHM=RSA-SHA256
UAE_NODE_KEY_ID=node-default
UAE_NODE_KEY_VERSION=v1
```

**Safe for**: container environments with secret injection
**Not safe for**: plain `.env` files in version control (never commit private keys)

### Future: KMS / HSM Providers

The `KeyProvider` abstract interface is designed for:
- AWS KMS: implement `sign()` to call `kms.sign()`
- GCP KMS: similar approach via `cloudkms.CryptoKeyVersions.asymmetricSign`
- HashiCorp Vault: use Transit secrets engine
- Hardware HSM: via PKCS#11 interface

To add a new provider, subclass `KeyProvider` and implement:
`get_key_info()`, `get_public_key_pem()`, `sign()`, `list_active_keys()`, `rotate_key()`

## Key Rotation

```python
from core.security.key_rotation import KeyRotationService

svc = KeyRotationService(provider)
event = svc.rotate("node-signing-key", reason="90-day scheduled rotation")
print(f"Rotated {event.old_version} → {event.new_version}")
```

After rotation:
1. Old signatures remain verifiable (old public key is preserved)
2. New signatures use the new key
3. Re-run node handshake with all federation peers to share new public key

## Revocation

```python
from core.security.revocation_store import RevocationStore

store = RevocationStore()
store.revoke("credential-id-123", "credential", revoked_by="admin", reason="student fraud")
assert store.is_revoked("credential-id-123")
```

## Signing Service Utility

```python
from core.security.signing_service import sign_payload_b64, verify_payload_b64

sig = sign_payload_b64(private_key_pem, {"claim_id": "c1", "action": "verify"})
valid = verify_payload_b64(public_key_pem, {"claim_id": "c1", "action": "verify"}, sig)
```

## Production Checklist

- [ ] Private keys are NOT committed to version control
- [ ] Private key files have `chmod 600` or equivalent protection
- [ ] `UAE_NODE_PRIVATE_KEY` is set via secrets manager (not `.env` file)
- [ ] Key rotation schedule is documented and scheduled (90 days recommended)
- [ ] Old public keys are retained for verifying historical signatures
- [ ] Revocation store is persisted (file or DB) across restarts
