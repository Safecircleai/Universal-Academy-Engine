# Credential Framework

## Overview

The UAE Credential Framework provides W3C Verifiable Credential (VC) 1.1-compatible credential issuance for course completions. Credentials are cryptographically signed, portable across nodes, and independently verifiable by any third party.

The framework is implemented in `core/credentials/credential_issuer.py` and backed by the `Credential` and `CredentialCompetency` models.

---

## Design Principles

1. **W3C VC compatibility** — credential documents conform to the Verifiable Credentials Data Model 1.1
2. **Competency-linked** — every credential lists the specific competencies the student has demonstrated
3. **Node-issued** — credentials are issued by a specific academy node with a known DID-style identifier
4. **Portable** — credentials can be exported as JSON or a Base64-encoded portable token
5. **Revocable** — credentials can be revoked while retaining the audit record
6. **Immutable audit** — revoked credentials are never deleted; the full history is preserved

---

## Credential Lifecycle

```
issue_credential()
      ↓
   [active]
      ↓
revoke_credential()
      ↓
   [revoked]  ← retained in database for audit
```

There is no "reinstate" operation. A new credential must be issued if revocation was in error.

---

## Credential Types

| Type | Description |
|------|-------------|
| `COMPLETION` | Course completed (default) |
| `PROFICIENCY` | Demonstrated skill proficiency |
| `MASTERY` | Expert-level mastery (highest tier) |
| `PARTICIPATION` | Participation only (no assessment) |
| `APPRENTICESHIP` | Vocational apprenticeship completion |

---

## W3C VC Document Structure

A credential exported via `export_json()` produces:

```json
{
  "@context": [
    "https://www.w3.org/2018/credentials/v1",
    "https://uae.academy/credentials/v1"
  ],
  "id": "urn:uae:credential:<credential_id>",
  "type": ["VerifiableCredential", "UAECourseCredential"],
  "issuer": "urn:uae:node:<issuing_node_id>",
  "issuanceDate": "2025-06-01T12:00:00Z",
  "credentialSubject": {
    "id": "urn:uae:student:<student_id>",
    "student_id": "student-001",
    "student_name": "Jane Doe",
    "course_id": "<course_id>",
    "course_title": "Fleet Maintenance Fundamentals",
    "academy_node": "cfrs_academy",
    "course_version": "1.0",
    "credential_type": "completion",
    "competencies_mastered": [
      {
        "competency_id": "<id>",
        "name": "Diagnose Cooling System Faults",
        "code": "NATEF-A8-01",
        "skill_level": "intermediate",
        "standard_reference": "NATEF Task A8-A-1"
      }
    ]
  },
  "proof": {
    "type": "RsaSignature2018",
    "created": "2025-06-01T12:00:00Z",
    "verificationMethod": "urn:uae:node:<node_id>#key-1",
    "proofPurpose": "assertionMethod",
    "jws": "<base64-encoded-signature>"
  }
}
```

---

## Issuing a Credential

```python
issuer = CredentialIssuer(session)

credential = await issuer.issue_credential(
    student_id="student-001",
    student_name="Jane Doe",
    student_email="jane@example.com",
    course_id=course.course_id,
    issuing_node_id=node.node_id,
    issued_by="admin",
    credential_type=CredentialType.COMPLETION,
    signing_private_key_pem=private_key_pem,  # optional
)
```

**Preconditions:**
- The course must be in `PublishingState.PUBLISHED` or `PublishingState.RESTRICTED`
- The `issuing_node_id` must reference an existing `AcademyNode`

**What happens internally:**
1. The course is loaded and its state is validated
2. All competencies addressed by the course (directly or via lessons) are collected
3. The W3C VC document is assembled
4. If a `signing_private_key_pem` is provided, the document is signed and a `proof` block is added
5. The credential hash is computed: `SHA-256(json.dumps(vc_doc, sort_keys=True))`
6. The `Credential` record is persisted
7. `CredentialCompetency` junction records are created for each competency

---

## Competency Collection

When a credential is issued, the system automatically collects all competencies addressed by the course:

- **Direct mappings:** `CompetencyMapping.course_id == course_id`
- **Via lessons:** `CompetencyMapping.lesson_id` in any lesson that belongs to a module of this course

Deduplication ensures each competency appears only once in `competencies_mastered`.

---

## Credential Verification

```python
result = await issuer.verify_credential(credential_id)
# {
#   "credential_id": "...",
#   "valid": True,
#   "student_id": "student-001",
#   "course_id": "...",
#   "credential_type": "completion",
#   "issued": "2025-06-01T12:00:00",
#   "errors": []
# }
```

Verification checks:
1. **Revocation status** — revoked credentials return `valid: False`
2. **Expiry** — expired credentials return `valid: False`
3. **Hash integrity** — the stored `credential_hash` is recomputed and compared

Cryptographic proof verification (checking the `proof.jws` signature) is a separate operation using `AttestationManager`.

---

## Export Formats

### JSON (W3C VC)

```python
doc = await issuer.export_json(credential_id)
```

Returns a Python dict representing the full W3C VC document. Suitable for machine-to-machine exchange and storage in a VC wallet.

### Portable Token

```python
token = await issuer.export_portable_token(credential_id)
```

Returns a Base64-URL encoded string of the JSON document. Suitable for embedding in QR codes, URLs, or email attachments.

**Decoding:**
```python
import base64, json
doc = json.loads(base64.urlsafe_b64decode(token + "==").decode())
```

---

## Revocation

```python
await issuer.revoke_credential(
    credential_id,
    reason="Student did not complete required practical assessment.",
    revoked_by="admin",
)
```

Revocation:
- Sets `is_revoked = True`, `revoked_at`, and `revocation_reason`
- Does **not** delete the credential record
- Adds a `credentialStatus` block to the exported JSON document:

```json
"credentialStatus": {
  "type": "RevocationList2020",
  "revoked": true,
  "revocationReason": "[admin] Student did not complete..."
}
```

---

## Student Credential Listing

```python
credentials = await issuer.list_student_credentials("student-001")
```

Returns all credentials issued to a student, ordered by `issue_date` descending.

---

## Credential Hash

The `credential_hash` is computed over the canonical W3C VC document (without the `proof` block):

```python
hashlib.sha256(json.dumps(vc_doc, sort_keys=True).encode()).hexdigest()
```

This hash can be shared publicly or stored in a transparency log to allow anyone to verify that the credential was not tampered with after issuance.

---

## Production Considerations

### Key Management
- Never pass private keys to the UAE server in production
- Use client-side signing: the credential document is assembled server-side, returned unsigned, signed client-side, then the signature is submitted back
- Consider integrating with a hardware security module (HSM) or KMS for node signing keys

### DID Integration
- The `issuer` field uses a `urn:uae:node:<id>` format by convention
- For full DID integration, replace with a `did:web` or `did:key` DID
- Register the node's public key in a DID document for fully decentralized verification

### Interoperability
- The credential document structure is compatible with VC wallets that support JSON-LD
- For selective disclosure or zero-knowledge proofs, consider integrating BBS+ signatures (not yet implemented)
