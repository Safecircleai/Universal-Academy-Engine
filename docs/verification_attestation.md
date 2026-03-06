# Verification Attestation

## Overview

The UAE verification attestation system transforms human claim verification from a database record into a **cryptographically provable event**. Any third party can independently verify that a specific reviewer signed a specific claim at a specific point in time, without trusting the UAE server itself.

---

## The Problem This Solves

Standard verification logs record *that* a review happened and *who* approved it. But these records are only as trustworthy as the database storing them. A compromised database could alter reviewer names or timestamps without detection.

Cryptographic attestations solve this by:
1. Binding the reviewer's identity to a public/private key pair they control
2. Having the reviewer sign a canonical payload that includes the claim hash
3. Storing only the *signature* on the server — not the private key
4. Allowing anyone with the public key to verify the signature independently

---

## Architecture

### ReviewerKey

Each reviewer registers a public key with the system:

```
ReviewerKey
├── key_id          (UUID)
├── node_id         (which node this reviewer belongs to)
├── reviewer_id     (identifier for the reviewer)
├── reviewer_name   (display name)
├── reviewer_role   (e.g., "lead_instructor", "sme_reviewer")
├── reviewer_credentials (e.g., ["ASE-P2", "NATEF-Certified"])
├── public_key_pem  (PEM-encoded RSA or Ed25519 public key)
├── key_fingerprint (SHA-256 of the public key, for deduplication)
├── signature_algorithm (RSA-SHA256, Ed25519, or ECDSA-P256)
└── valid_until     (optional key expiry date)
```

The private key **never leaves the reviewer's possession**. The server only stores the public key.

### VerificationAttestation

When a reviewer verifies a claim, an attestation is created:

```
VerificationAttestation
├── attestation_id         (UUID)
├── claim_id               (the claim being attested)
├── log_id                 (link to the VerificationLog entry, optional)
├── reviewer_key_id        (FK to ReviewerKey)
├── claim_hash             (SHA-256 of the claim statement)
├── reviewer_signature     (Base64-encoded signature)
├── signature_algorithm    (algorithm used)
├── signed_payload         (the exact canonical JSON that was signed)
├── reviewer_id            (redundant reference for query convenience)
├── reviewer_role          (role at time of signing)
├── verification_reason    (human-readable justification)
├── signature_verified     (Boolean — result of server-side verification)
└── verified_at            (timestamp of successful verification)
```

---

## Signing Protocol

### Step 1: Build the Canonical Payload

The canonical payload is a deterministic JSON dict:

```json
{
  "claim_id": "...",
  "claim_hash": "sha256-of-claim-statement",
  "reviewer_id": "reviewer_alice",
  "schema_version": "uae-attestation-v1"
}
```

The payload is serialized with `sort_keys=True` to ensure consistent ordering across implementations.

### Step 2: Sign the Payload

The reviewer signs the canonical JSON string with their private key:

```python
# Using RSA-SHA256 (via `cryptography` library)
signature = private_key.sign(
    payload.encode(),
    padding.PKCS1v15(),
    hashes.SHA256(),
)
signature_b64 = base64.b64encode(signature).decode()
```

The `AttestationManager.sign_payload(private_key_pem, payload)` utility handles this for development/testing workflows.

### Step 3: Submit the Attestation

The Base64-encoded signature is submitted to `create_attestation()`. The server:
1. Retrieves the claim and computes its hash
2. Reconstructs the canonical payload
3. Verifies the signature against the registered public key
4. Stores the result with `signature_verified=True/False`

---

## Supported Algorithms

| Algorithm | Key Type | Status |
|-----------|----------|--------|
| `RSA-SHA256` | RSA 2048+ | Default |
| `Ed25519` | Ed25519 | Preferred for new deployments |
| `ECDSA-P256` | EC P-256 | Supported |
| `HMAC-SHA256` | Shared secret | Dev/test fallback only |

The HMAC-SHA256 fallback is used when the `cryptography` Python package is not installed. It is **not suitable for production** as it requires the server to hold the signing secret.

---

## Development Key Generation

For development and testing, the `AttestationManager` provides:

```python
priv_pem, pub_pem = AttestationManager.generate_dev_key_pair()
```

This generates a 2048-bit RSA key pair. **Do not use in production.** For production:
- Generate keys offline using `openssl genrsa` or equivalent
- Store private keys in a secrets manager (Vault, AWS KMS, GCP KMS)
- Rotate keys on a defined schedule

---

## Re-verification

Any attestation can be re-verified at any time:

```python
result = await manager.verify_attestation(attestation_id)
# {
#   "valid": True,
#   "attestation_id": "...",
#   "claim_id": "...",
#   "reviewer_id": "reviewer_alice",
#   "algorithm": "RSA-SHA256",
#   "verified_at": "2025-01-15T10:30:00",
#   "errors": []
# }
```

This re-runs the cryptographic verification against the stored public key and signed payload.

---

## Claim Hash

The claim hash is computed as:

```python
hashlib.sha256(claim.statement.encode("utf-8")).hexdigest()
```

This hash is stored directly on the `Claim` model as `claim_hash`, enabling independent verification without querying the attestation table.

---

## Privacy Considerations

- Reviewer names and credentials are stored in plaintext in `ReviewerKey`
- For privacy-sensitive deployments, consider using pseudonymous reviewer IDs and storing PII in an external identity system
- Public keys are, by definition, public — publishing them in a transparency log is safe and recommended
