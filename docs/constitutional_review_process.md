# UAE v4 — Constitutional Review Process

## Overview

The constitutional review workflow routes doctrine-impacting claims through
a multi-step human governance process before they can be enacted.

## Workflow States

```
             detect conflict / precedence violation
                          │
                          ▼
                CONSTITUTIONAL_REVIEW_REQUIRED
                          │
              constitutional_reviewer picks up
                          │
                          ▼
             CONSTITUTIONAL_REVIEW_IN_PROGRESS
                          │
              governance_council renders decision
                          │
                          ▼
             CONSTITUTIONAL_DECISION_RECORDED
                    │              │
            council approves    council rejects
                    │              │
                    ▼              ▼
                VERIFIED       DEPRECATED
```

## Who Can Perform Each Step?

| Step | Required Role |
|------|--------------|
| Trigger review | `doctrine_steward` |
| Conduct review | `constitutional_reviewer` |
| Record decision | `governance_council` |
| Read review status | `auditor` |

## When Is Constitutional Review Triggered?

1. **Automatic** — `ConflictDetector` flags the claim during:
   - `ClaimFederationProtocol.import_claim()` — doctrine-bearing federation imports
   - Agent worker output validation — `BaseWorker._check_doctrine_safeguards()`

2. **Manual** — A `doctrine_steward` transitions a claim to
   `constitutional_review_required` via `ClaimLedger.update_claim_status()`

## Valid Transitions

```python
DRAFT → CONSTITUTIONAL_REVIEW_REQUIRED
VERIFIED → CONSTITUTIONAL_REVIEW_REQUIRED
CONTESTED → CONSTITUTIONAL_REVIEW_REQUIRED

CONSTITUTIONAL_REVIEW_REQUIRED → CONSTITUTIONAL_REVIEW_IN_PROGRESS
CONSTITUTIONAL_REVIEW_REQUIRED → DEPRECATED  # abandoned without review

CONSTITUTIONAL_REVIEW_IN_PROGRESS → CONSTITUTIONAL_DECISION_RECORDED
CONSTITUTIONAL_REVIEW_IN_PROGRESS → DEPRECATED  # abandoned

CONSTITUTIONAL_DECISION_RECORDED → VERIFIED  # approved
CONSTITUTIONAL_DECISION_RECORDED → DEPRECATED  # rejected
```

## GovernanceDecision Record

When the governance council makes a decision, a `GovernanceDecision` record
is created:

```python
from database.schemas.models import GovernanceDecision

decision = GovernanceDecision(
    claim_id="claim-uuid",
    node_id="node-a",
    reviewers=["alice@council", "bob@council", "carol@council"],
    decision_type="approve",          # approve / reject / defer / modify
    decision_summary="Claim reviewed. Constitutional alignment confirmed.",
    evidence_sources=["src-001", "src-002"],
    final_outcome="Claim approved for verified status.",
    doctrine_precedence_invoked="governance_spec",
    conflict_resolution_method="majority_vote",
    recorded_by="carol@council",
)
```

## Archive Recording

Every step in the constitutional review process is recorded in the
`InstitutionalArchive`:

```python
from core.memory.institutional_archive import InstitutionalArchive

archive = InstitutionalArchive(session)

# When review is triggered
await archive.record(
    event_type="constitutional_review_triggered",
    subject_id=claim_id,
    subject_type="claim",
    event_summary=f"Claim {claim_number} requires constitutional review: {reason}",
    preceding_state={"status": "verified"},
    resulting_state={"status": "constitutional_review_required"},
    actor_id="system",
)

# When decision is recorded
await archive.record(
    event_type="governance_decision_recorded",
    subject_id=claim_id,
    subject_type="claim",
    event_summary=f"Council decision: {decision_type}",
    resulting_state={"decision_id": decision.decision_id, "outcome": final_outcome},
    actor_id=recorded_by,
)
```

## Querying the Review Trail

```python
# Get the full constitutional review trail for a claim
trail = await archive.get_constitutional_review_trail(claim_id)
for entry in trail:
    print(f"{entry.timestamp}: {entry.event_type} — {entry.event_summary}")
```
