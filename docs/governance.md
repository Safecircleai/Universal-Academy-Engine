# UAE Governance Model

## Principles

The Universal Academy Engine operates under a **Human-AI Governance** model. AI agents accelerate the knowledge pipeline, but humans retain final authority over:

1. What knowledge is considered verified
2. What curriculum is published to learners
3. How conflicts between claims are resolved
4. When claims become deprecated

---

## The Verification Gate

No claim can be referenced in a lesson until it has been explicitly verified by a human reviewer. The pipeline enforces this at the database level:

```
Draft Claim → [Human Review] → Verified Claim → Lesson Reference
```

The `CurriculumBuilder.add_lesson()` method raises a `CurriculumError` if any `claim_id` in the lesson is not in `verified` status. This check cannot be bypassed through the API.

---

## Claim Status Lifecycle

```
              ┌─────────────────┐
              │      DRAFT      │  ← Created by Knowledge Cartographer
              └────────┬────────┘
                       │  (human verifies)
              ┌────────▼────────┐
              │    VERIFIED     │  ← May be used in lessons
              └────────┬────────┘
                       │  (conflict detected or knowledge updated)
    ┌──────────────────▼──────────┐
    │         CONTESTED           │  ← Under review
    └──────────────────┬──────────┘
                       │  (resolved or superseded)
              ┌────────▼────────┐
              │   DEPRECATED    │  ← No longer active; history preserved
              └─────────────────┘
```

Valid transitions:
- `draft` → `verified`, `contested`, `deprecated`
- `verified` → `contested`, `deprecated`
- `contested` → `verified`, `deprecated`
- `deprecated` → *(terminal state)*

---

## Human Override

Any human reviewer with appropriate access can override an AI-assigned status at any time:

```
POST /api/v1/claims/{claim_id}/override
{
  "new_status": "deprecated",
  "reviewer": "dr_jane_smith",
  "reason": "Superseded by 2024 FMCSA regulation update."
}
```

The override creates:
1. An immutable `ClaimRevision` record with `[HUMAN OVERRIDE]` prefix
2. A `VerificationLog` entry with `is_ai_review: false`

---

## High-Confidence Escalation

Claims with a `confidence_score ≥ 0.95` (configurable) are automatically flagged for mandatory human review before they can influence published curriculum. This prevents AI-generated high-confidence errors from reaching learners unchecked.

---

## Integrity Auditing

The Integrity Auditor agent runs periodic scans:

| Mode | Description |
|------|-------------|
| `full` | Complete audit: conflicts + outdated + escalations |
| `conflicts_only` | Detect contradictory claims only |
| `outdated_only` | Flag claims not updated within threshold |
| `escalate` | Escalate high-confidence claims for human review |

Audit results are stored in `IntegrityReport` records and are accessible via:
```
GET /api/v1/verification/reports
```

---

## Human Review Queue

All items requiring human review appear in the pending queue:

```
GET /api/v1/verification/pending
```

Reviewers can approve or reject:
```
POST /api/v1/verification/approve/{log_id}
POST /api/v1/verification/reject/{log_id}
```

---

## Audit Trail

Every change to every claim is recorded and queryable:

```
GET /api/v1/claims/{claim_id}/audit
```

Returns the complete revision history and all verification log entries for the claim.

---

## Data Retention

- Claim revisions are **immutable** and never deleted
- Deprecated claims are retained with full history
- Agent run logs are retained indefinitely
- Integrity reports are retained indefinitely

---

## Contribution Guidelines

When contributing to the UAE codebase:

1. **Never bypass the verification gate** — do not create lessons with non-verified claims
2. **Document architectural changes** in `docs/architecture_suggestions.md` before implementation
3. **All schema changes require migrations** — use Alembic
4. **Agent changes must not remove governance hooks** — `BaseAgent` lifecycle must be preserved
5. **Test governance invariants** — the test suite must include negative cases for governance violations
