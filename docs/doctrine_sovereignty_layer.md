# UAE v4 — Doctrine Sovereignty Layer

## Overview

UAE v4 elevates the platform from a governed knowledge system into a
**constitutional knowledge infrastructure**. It introduces an explicit
doctrine hierarchy, conflict detection, constitutional review workflows,
and immutable institutional memory.

## Core Concepts

### What is "Doctrine"?

In UAE, *doctrine* refers to the body of knowledge statements that are
so foundational they require special governance protections:

- **Immutable core** — foundational axioms that cannot be changed without
  unanimous governance council approval
- **Constitutional doctrine** — the organisation's knowledge constitution
- **Governance spec** — how governance processes work
- Everything else follows standard claim verification

### Why Doctrine Sovereignty?

Without a precedence hierarchy, a low-quality external reference could
theoretically `supersede` a verified constitutional doctrine claim. The
Doctrine Sovereignty Layer prevents this by:

1. Classifying every source with a `SourceType`
2. Enforcing precedence rules at import and review time
3. Requiring constitutional review for doctrine-altering claims
4. Recording every change in an immutable institutional archive

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   UAE v4 Knowledge Stack                 │
├──────────────────────────────────────────────────────────┤
│  core/doctrine/                                          │
│    precedence_engine.py   — hierarchy enforcement        │
│    conflict_detector.py   — detect constitutional issues │
│    dependency_graph.py    — impact analysis              │
├──────────────────────────────────────────────────────────┤
│  core/memory/                                            │
│    institutional_archive.py — immutable event log        │
│    temporal_views.py        — time-travel queries        │
├──────────────────────────────────────────────────────────┤
│  database models (new in v4)                             │
│    SourceType              — 8-value source classification│
│    ClaimClassification     — 7-value claim semantics     │
│    ClaimStatus (extended)  — 3 constitutional states     │
│    GovernanceDecision      — council decision record     │
│    InstitutionalArchiveEntry — immutable event log table │
└──────────────────────────────────────────────────────────┘
```

## New Roles

| Role | Description |
|------|-------------|
| `doctrine_steward` | Manages source classification and doctrine precedence |
| `constitutional_reviewer` | Conducts constitutional review of claims |
| `governance_council` | Records final governance decisions |

## New ClaimStatus Values

| Status | Meaning |
|--------|---------|
| `constitutional_review_required` | Claim has been flagged for doctrine review |
| `constitutional_review_in_progress` | Review is actively being conducted |
| `constitutional_decision_recorded` | Council has rendered a decision |

## Invariants

1. **Immutable core cannot be overridden** — any claim that attempts to
   `supersede`, `conflict_with`, or `deprecated_by` an immutable core claim
   is automatically flagged for constitutional review.

2. **Lower-precedence sources cannot override higher** — a curriculum claim
   cannot supersede a constitutional doctrine claim without council approval.

3. **No agent autonomy on doctrine** — `BaseWorker.check_doctrine_safeguards()`
   ensures agents cannot autonomously propose doctrine overrides.

4. **All doctrine events are archived** — `InstitutionalArchive` records every
   significant knowledge evolution event. No archive entries are ever modified
   or deleted.

5. **All v3 invariants are preserved** — claims must be `verified` before
   publishing; credentials only issue from published curriculum; etc.

## Quick Start

```python
from core.doctrine.precedence_engine import PrecedenceEngine
from database.schemas.models import SourceType, ClaimClassification

engine = PrecedenceEngine()

# Check if a curriculum claim can supersede constitutional doctrine
result = engine.check(
    incoming_source_type=SourceType.CURRICULUM,
    classification=ClaimClassification.SUPERSEDES,
    incumbent_source_type=SourceType.CONSTITUTIONAL_DOCTRINE,
)
print(result.requires_constitutional_review)  # True
print(result.reason)
```

## Database Migration

Run migration 003 to add v4 schema extensions:

```bash
alembic -c database/migrations/alembic.ini upgrade head
```

The migration is idempotent — safe to run on existing v3 databases.
