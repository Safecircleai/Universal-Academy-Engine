# UAE v4 — Temporal Knowledge Views

## Overview

`TemporalKnowledgeView` reconstructs the state of knowledge at any point
in time. It enables:

- "What did the verified knowledge base look like on 2024-01-01?"
- "Which claims were verified when course X was published?"
- "What was the doctrine before the constitutional review?"

## How It Works

### Claim State Reconstruction

For each claim, the temporal view:

1. Checks whether the claim existed at the requested timestamp
   (`claim.created_at <= as_of`)
2. Finds the most recent `ClaimRevision` at or before `as_of`
3. Returns the `updated_version` from that revision as the status at
   that point in time
4. If no revision exists, the claim was in its initial `DRAFT` state

### Snapshot Construction

`snapshot_at()` reconstructs the full knowledge snapshot by:

1. Fetching all claims created before `as_of`
2. Reconstructing each claim's status at that time
3. Grouping claims into `verified_claims` and `contested_claims`
4. Fetching doctrine events from the `InstitutionalArchive` up to `as_of`

## Usage

```python
from datetime import datetime
from core.memory.temporal_views import TemporalKnowledgeView

view = TemporalKnowledgeView(session)

# Get state of a specific claim at a point in time
state = await view.get_claim_state_at(
    claim_id="claim-uuid",
    as_of=datetime(2024, 6, 1),
)
print(state.status)             # "verified", "draft", etc.
print(state.source_type)        # "governance_spec"
print(state.as_of)              # datetime(2024, 6, 1)
print(state.derived_from_revision)  # revision_id or None

# Full knowledge snapshot
snapshot = await view.snapshot_at(
    as_of=datetime(2024, 1, 1),
    node_id="node-a",
    include_doctrine_events=True,
)
print(snapshot.summary)
# {
#   "as_of": "2024-01-01T00:00:00",
#   "node_id": "node-a",
#   "total_claims": 142,
#   "verified_count": 118,
#   "contested_count": 3,
#   "doctrine_events_count": 7,
# }

# Full timeline for a claim (merged revisions + archive events)
timeline = await view.get_doctrine_timeline("claim-uuid")
for event in timeline:
    print(f"{event['timestamp']}: {event['event_type']}")
```

## TemporalClaimState Fields

| Field | Type | Description |
|-------|------|-------------|
| `claim_id` | str | Claim primary key |
| `claim_number` | str | Human-readable number (CLM000042) |
| `statement` | str | The claim text at time of query |
| `status` | str | Status at `as_of` timestamp |
| `confidence_score` | float | Confidence score |
| `source_id` | str | Source document primary key |
| `source_type` | str | SourceType value |
| `claim_classification` | str | ClaimClassification value |
| `requires_constitutional_review` | bool | Doctrine review flag |
| `version` | int | Claim version at query time |
| `as_of` | datetime | The queried timestamp |
| `derived_from_revision` | str | Revision ID used for reconstruction |

## Limitations

- **Statement text** is always current — only status is reconstructed.
  For full text-level history, check `ClaimRevision.change_reason`.
- **Performance** — `snapshot_at()` has O(n) complexity over all claims.
  Use the `limit` parameter for large deployments.
- **Precision** — Times are stored in UTC. Compare using UTC datetimes.
