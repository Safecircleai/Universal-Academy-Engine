# Federation Architecture

## Overview

The Universal Academy Engine (UAE) is designed as a **federated knowledge infrastructure** — a network of independently governed academy nodes that can share, import, contest, and adopt knowledge claims while preserving each node's autonomy and governance policy.

Federation does not require centralized coordination. Each node operates independently and participates in the network on its own terms. The federation layer is a protocol, not a platform.

---

## Core Concepts

### Academy Node

An `AcademyNode` represents an independently operated knowledge institution — a vocational academy, charter school, university, civic research center, or any other recognized body that maintains a local source registry and claim ledger.

Each node has:
- A unique `node_id` (UUID)
- A `node_name` and `node_type`
- An optional RSA/Ed25519 `public_key_pem` for cryptographic identification
- A `NodeGovernancePolicy` that controls what sources, claims, and operations are permitted
- A federation membership flag (`is_federation_member`) and timestamp (`joined_federation_at`)

### Node Types

| Type | Description |
|------|-------------|
| `VOCATIONAL_ACADEMY` | Skills-based training institutions (default for CFRS) |
| `CHARTER_SCHOOL` | K-12 charter institutions |
| `UNIVERSITY` | Degree-granting institutions |
| `CIVIC_RESEARCH_CENTER` | Policy and civic knowledge bodies |
| `STANDARDS_BODY` | Official standards publishing organizations |
| `GOVERNMENT_AGENCY` | Regulatory and governmental bodies |

---

## Claim Categories

Claims carry a `claim_category` that reflects their federation status:

| Category | Meaning |
|----------|---------|
| `LOCAL` | Claim exists only within the originating node |
| `SHARED` | Claim has been published to the federation |
| `IMPORTED` | Claim was imported from another node |
| `CONTESTED` | Claim is under active dispute from another node |

---

## Federation Protocol

The `ClaimFederationProtocol` implements four operations:

### 1. Publish (`publish_claim`)

A node publishes a verified claim to the federation, making it available for other nodes to import.

**Preconditions:**
- Claim must be in `ClaimStatus.VERIFIED` state
- The publishing node's `NodeGovernancePolicy.allow_claim_publication` must be `True`
- The claim's `origin_node_id` must match the publishing node

**Effect:**
- `claim.claim_category` → `ClaimCategory.SHARED`
- `claim.publishing_node_id` set to the publishing node
- A `FederatedClaimRecord` with `action="publish"` is logged

### 2. Import (`import_claim`)

A node imports a shared claim from the federation into its local knowledge base.

**Preconditions:**
- Claim must be in `ClaimCategory.SHARED` or `ClaimCategory.IMPORTED` state

**Effect:**
- A local copy or reference is established
- `claim_category` may be updated to `IMPORTED`
- A `FederatedClaimRecord` with `action="import"` is logged for the importing node

### 3. Contest (`contest_claim`)

A node contests a shared claim on the basis of conflicting evidence.

**Effect:**
- `claim.claim_category` → `ClaimCategory.CONTESTED`
- A `FederatedClaimRecord` with `action="contest"` is logged, including the stated reason
- The origin node is notified via the federation event log

### 4. Adopt (`adopt_claim`)

A contesting node resolves the dispute by adopting the claim (accepting it as valid under a new interpretation).

**Effect:**
- `claim.claim_category` → `ClaimCategory.IMPORTED`
- Resolution notes are recorded in the `FederatedClaimRecord`
- The claim is no longer in CONTESTED state

---

## Governance Policy Per Node

Each node maintains a `NodeGovernancePolicy` that governs what it will accept:

| Field | Default | Description |
|-------|---------|-------------|
| `minimum_source_tier` | `TIER3` | Minimum trust tier required for sources |
| `required_reviewers` | `1` | Minimum number of reviewers for claim verification |
| `verification_threshold` | `0.75` | Minimum confidence score for auto-verification |
| `require_approval_to_publish` | `False` | Whether human approval is required before publishing |
| `allow_claim_publication` | `False` | Whether this node can publish claims to the federation |
| `allow_imported_claims` | `True` | Whether this node accepts imported claims |

Policy compliance is checked before federation operations are permitted.

---

## Federation Event Log

All federation operations are immutably logged as `FederatedClaimRecord` entries. Each record captures:
- `claim_id` — the affected claim
- `action` — publish, import, contest, or adopt
- `source_node_id` — the node initiating the action
- `target_node_id` — the node receiving or affected by the action (for imports)
- `timestamp` — UTC timestamp of the event
- `reason` / `resolution_notes` — human-readable context
- `claim_snapshot` — JSON snapshot of the claim state at the time of the event

This log is the foundation for federation audit reports.

---

## Inter-Node Trust Model

Nodes do not inherently trust each other. Trust is established through:

1. **Governance policy compliance** — importing nodes check that the source meets their minimum trust tier
2. **Claim verification status** — only `VERIFIED` claims can be published
3. **Cryptographic attestation** — the origin node's public key can be used to verify claim signing (see `docs/verification_attestation.md`)
4. **Federation membership** — nodes may restrict imports to federation members only

---

## Node Lifecycle

```
register_node()
    ↓
[active, non-member]
    ↓
admit_to_federation()
    ↓
[active, federation member]
    ↓
deactivate_node()
    ↓
[inactive]
```

Deactivated nodes retain all historical data for audit purposes. Their claims remain accessible but no new federation operations are permitted.

---

## Scalability Considerations

The federation protocol is designed to work at any scale:

- **Single-node mode:** No federation activity; all claims are `LOCAL`
- **Small federation:** 2–10 nodes sharing domain-specific knowledge
- **Large federation:** Hundreds of nodes across jurisdictions; governance policies enforce quality gates at each boundary

For production deployments, consider running PostgreSQL and using a message queue (e.g., Redis Streams, NATS) to propagate federation events asynchronously across nodes.
