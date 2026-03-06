# Claim Federation Protocol

## Overview

The Claim Federation Protocol defines the rules, operations, and state transitions governing how knowledge claims move between academy nodes. It is implemented in `core/federation/claim_federation.py` and provides the `ClaimFederationProtocol` class.

---

## Protocol Goals

1. **Verifiable provenance** — every claim imported from the network carries the identity of the originating node
2. **Local autonomy** — each node applies its own governance policy before accepting an imported claim
3. **Dispute resolution** — any node can contest a claim; the contest mechanism prevents silent propagation of errors
4. **Immutable audit trail** — all federation operations are logged as `FederatedClaimRecord` entries that cannot be modified after creation

---

## Claim State Machine (Federation Dimension)

```
LOCAL
  │
  │  publish_claim()
  ▼
SHARED ──────────────────────────────────────────────────┐
  │                                                       │
  │  import_claim()            contest_claim()            │
  ▼                                ▼                      │
IMPORTED                       CONTESTED                  │
                                    │                     │
                                    │  adopt_claim()      │
                                    ▼                     │
                                IMPORTED ◄────────────────┘
```

---

## Operations

### `publish_claim(claim_id, node_id)`

Publishes a verified claim from a node to the federation.

**Preconditions:**
- `Claim.status == ClaimStatus.VERIFIED`
- `NodeGovernancePolicy.allow_claim_publication == True` for the publishing node
- The claim's `origin_node_id` must equal `node_id`

**State transition:**
- `claim.claim_category` → `SHARED`
- `claim.publishing_node_id` → `node_id`

**Logged event:**
```json
{
  "action": "publish",
  "source_node_id": "<node_id>",
  "target_node_id": null,
  "claim_snapshot": { ... }
}
```

**Raises:** `FederationError` if preconditions are not met.

---

### `import_claim(claim_id, importing_node_id)`

Imports a shared claim into a node's knowledge base.

**Preconditions:**
- `claim.claim_category` must be `SHARED` or `IMPORTED`

**State transition:**
- `claim.claim_category` → `IMPORTED`
- `claim.publishing_node_id` is preserved (origin node retained)

**Logged event:**
```json
{
  "action": "import",
  "source_node_id": "<origin_node>",
  "target_node_id": "<importing_node_id>",
  "claim_snapshot": { ... }
}
```

**Returns:** `(Claim, FederatedClaimRecord)` tuple.

---

### `contest_claim(claim_id, contesting_node_id, reason)`

Flags a shared claim as contested, blocking further propagation until resolved.

**Preconditions:**
- `claim.claim_category` must be `SHARED` or `IMPORTED`

**State transition:**
- `claim.claim_category` → `CONTESTED`

**Logged event:**
```json
{
  "action": "contest",
  "source_node_id": "<contesting_node_id>",
  "reason": "Evidence contradicts this claim under FMCSA 2024 update.",
  "claim_snapshot": { ... }
}
```

---

### `adopt_claim(claim_id, adopting_node_id, resolution_notes)`

Resolves a contest by adopting the claim as valid under a new interpretation.

**Preconditions:**
- `claim.claim_category` must be `CONTESTED`

**State transition:**
- `claim.claim_category` → `IMPORTED`

**Logged event:**
```json
{
  "action": "adopt",
  "source_node_id": "<adopting_node_id>",
  "resolution_notes": "Reviewed and confirmed valid under new interpretation.",
  "claim_snapshot": { ... }
}
```

---

## FederatedClaimRecord Schema

Every federation operation produces an immutable `FederatedClaimRecord`:

| Field | Type | Description |
|-------|------|-------------|
| `record_id` | UUID | Primary key |
| `claim_id` | FK | The affected claim |
| `action` | String | publish / import / contest / adopt |
| `source_node_id` | FK | Node initiating the action |
| `target_node_id` | FK (nullable) | Destination node (for imports) |
| `reason` | Text (nullable) | Human justification (for contests) |
| `resolution_notes` | Text (nullable) | Resolution context (for adopts) |
| `claim_snapshot` | JSON | Full claim state at the time of the event |
| `timestamp` | DateTime | UTC timestamp |

Records are **append-only**. They are never modified after creation.

---

## Claim Snapshot Format

The `claim_snapshot` field captures the full state of the claim at the moment of the federation event:

```json
{
  "claim_id": "...",
  "claim_number": "CLM-00042",
  "statement": "The thermostat regulates coolant flow.",
  "status": "verified",
  "claim_category": "shared",
  "confidence_score": 0.87,
  "version": 1,
  "origin_node_id": "...",
  "publishing_node_id": "...",
  "claim_hash": "sha256-...",
  "citation_location": "p.42"
}
```

This snapshot is permanent and cannot be altered even if the claim is later deprecated or superseded.

---

## Federation Event Queries

```python
protocol = ClaimFederationProtocol(session)

# All events for a specific claim
events = await protocol.list_federation_events(claim_id=claim.claim_id)

# All events for a specific node
events = await protocol.list_federation_events(node_id=node.node_id)

# All publish events across the federation
events = await protocol.list_federation_events(action="publish")
```

---

## Error Handling

All protocol violations raise `FederationError` with a descriptive message:

| Condition | Error message |
|-----------|---------------|
| Claim not verified | `"Only verified claims may be published to the federation."` |
| Publication not allowed | `"Node governance policy does not allow claim publication."` |
| Claim not shared | `"Claim must be in SHARED or IMPORTED state to be imported."` |
| Contest on non-shared | `"Only SHARED or IMPORTED claims may be contested."` |
| Adopt non-contested | `"Only CONTESTED claims may be adopted."` |

---

## Governance Policy Integration

Before any federation operation, the `NodeGovernancePolicy` is checked:

```python
policy = await manager.check_policy_compliance(
    node_id, source_tier=source.trust_tier
)
if not policy["compliant"]:
    raise FederationError(f"Policy violations: {policy['violations']}")
```

Nodes may configure:
- `minimum_source_tier` — reject claims from lower-tier sources
- `allow_claim_publication` — gate publishing behind explicit enablement
- `allow_imported_claims` — opt out of the federation entirely
- `required_reviewers` — require N reviewers before publication is permitted
