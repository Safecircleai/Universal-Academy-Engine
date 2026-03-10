# UAE v4 — Institutional Memory

## Overview

The `InstitutionalArchive` is a write-once, append-only record of every
significant knowledge evolution event in the UAE system. It provides:

- **Immutability** — entries are never modified or deleted
- **Integrity** — every entry has a content hash for tamper detection
- **Completeness** — all doctrine-relevant events are captured
- **Auditability** — full provenance trail for any claim or source

## Architecture

```
core/memory/institutional_archive.py
  InstitutionalArchive
    record()                    — create a new archive entry
    get_history()               — entries for a subject
    get_by_event_type()         — entries by event category
    get_constitutional_review_trail() — review trail for a claim
    verify_entry_integrity()    — check content hash

database table: institutional_archive
  entry_id, event_type, subject_id, subject_type, node_id,
  actor_id, event_summary, evidence_payload, preceding_state,
  resulting_state, content_hash, timestamp
```

## Event Types

| Event Type | When Recorded |
|-----------|---------------|
| `claim_status_transition` | Any claim status change |
| `constitutional_review_triggered` | Claim routed to constitutional review |
| `constitutional_review_started` | Reviewer picks up the claim |
| `governance_decision_recorded` | Council renders a decision |
| `doctrine_conflict_detected` | ConflictDetector finds a conflict |
| `source_reclassified` | Source type is changed |
| `federation_import_doctrine` | Doctrine-bearing claim imported from peer |

## Usage

```python
from core.memory.institutional_archive import InstitutionalArchive

archive = InstitutionalArchive(session)

# Record an event
entry = await archive.record(
    event_type="claim_status_transition",
    subject_id=claim_id,
    subject_type="claim",
    event_summary="CLM000042 transitioned draft → constitutional_review_required",
    preceding_state={"status": "draft", "version": 1},
    resulting_state={"status": "constitutional_review_required", "version": 2},
    actor_id="alice@node",
    node_id="node-a",
)
print(entry.content_hash)  # SHA-256 of the entry content

# Query history for a claim
history = await archive.get_history(claim_id, subject_type="claim")

# Verify integrity of a stored entry
is_valid = await archive.verify_entry_integrity(entry.entry_id)
assert is_valid  # True if entry has not been modified
```

## Content Integrity

Every entry's `content_hash` is computed as:

```python
import hashlib, json

payload = json.dumps({
    "event_type": event_type,
    "subject_id": subject_id,
    "event_summary": event_summary,
    "preceding_state": preceding_state,
    "resulting_state": resulting_state,
}, sort_keys=True, default=str)
content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

`verify_entry_integrity()` recomputes this hash and compares it to the
stored value. Any database-level tampering will be detected.

## Governance Implications

The institutional archive is the **ground truth** for all doctrine evolution.
In disputes about when a change was made, by whom, and under what authority,
the archive entry is the authoritative record.

Archive entries are read by:
- Audit reports (`POST /api/v1/audit/run`)
- Temporal knowledge views (`TemporalKnowledgeView`)
- Constitutional review trails
- Federation dispute resolution
