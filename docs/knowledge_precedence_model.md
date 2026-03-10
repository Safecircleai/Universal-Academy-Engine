# UAE v4 — Knowledge Precedence Model

## Precedence Hierarchy

The UAE knowledge precedence hierarchy determines the authority of a claim
based on the `SourceType` of its source document. Higher-precedence source
types have more authority and are harder to override.

| Level | SourceType | Description |
|-------|-----------|-------------|
| 0 (highest) | `immutable_core` | Foundational axioms; cannot be superseded |
| 1 | `constitutional_doctrine` | Organisation knowledge constitution |
| 2 | `governance_spec` | Governance procedures and rules |
| 3 | `technical_spec` | Technical standards and specifications |
| 4 | `implementation_spec` | Implementation guides and how-tos |
| 5 | `commentary` | Expert commentary and analysis |
| 6 | `curriculum` | Curriculum and training materials |
| 7 (lowest) | `external_reference` | Third-party or external references |

## Rules

### Rule 1 — Higher Cannot Be Overridden by Lower (Without Review)

A claim from a *lower-precedence* source may not `supersede` or
`conflict_with` a claim from a *higher-precedence* source without
triggering constitutional review.

```
curriculum (6) supersedes constitutional_doctrine (1) → REVIEW REQUIRED
constitutional_doctrine (1) supersedes curriculum (6) → OK
```

### Rule 2 — `conflicts_with` Always Triggers Review

Any claim classified as `conflicts_with` triggers constitutional review,
regardless of the precedence relationship. Conflicts must be resolved
through the governance workflow.

### Rule 3 — Immutable Core Is Protected

Claims targeting `immutable_core` with `supersedes`, `deprecated_by`, or
`conflicts_with` always require governance council approval. These are the
foundational truths of the system.

### Rule 4 — Agents Cannot Override Doctrine

The `BaseWorker.check_doctrine_safeguards()` enforces that no agent can
autonomously propose:
- A `conflicts_with` or `supersedes` classification
- Modifications to `immutable_core`, `constitutional_doctrine`, or
  `governance_spec` source-type claims

## PrecedenceEngine Usage

```python
from core.doctrine.precedence_engine import PrecedenceEngine
from database.schemas.models import SourceType, ClaimClassification

engine = PrecedenceEngine()

# Check a specific interaction
result = engine.check(
    incoming_source_type=SourceType.TECHNICAL_SPEC,
    classification=ClaimClassification.CLARIFIES,
    incumbent_source_type=SourceType.GOVERNANCE_SPEC,
)
# result.requires_constitutional_review → False (clarification is allowed)

# Get full hierarchy
for entry in engine.get_hierarchy():
    print(f"Level {entry['precedence_level']}: {entry['source_type']}")
```

## ClaimClassification Values

| Classification | Meaning | Review Trigger |
|---------------|---------|----------------|
| `reinforces` | Supports existing doctrine | Never |
| `clarifies` | Adds precision | Never |
| `operationalizes` | Provides implementation | Never |
| `extends` | Adds new domain | Never |
| `conflicts_with` | Contradicts doctrine | **Always** |
| `supersedes` | Replaces doctrine | When lower→higher |
| `deprecated_by` | Replaced by another | When targeting protected |

## Impact Analysis

Use `DoctrineDependencyGraph` to assess the downstream impact of changing
a doctrine claim:

```python
from core.doctrine.dependency_graph import DoctrineDependencyGraph

graph = DoctrineDependencyGraph(session)
report = await graph.impact_analysis("claim-uuid")

print(f"Affected claims: {len(report.affected_claims)}")
print(f"Affected courses: {len(report.affected_courses)}")
print(f"Requires doctrine review: {report.requires_doctrine_review}")
```
