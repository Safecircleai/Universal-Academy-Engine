# UAE Architecture

## Overview

The Universal Academy Engine is a five-layer knowledge pipeline:

```
Layer 1: Source Registry      ─ Trusted document management
Layer 2: Claim Ledger         ─ Atomic knowledge statements
Layer 3: Knowledge Graph      ─ Concept relationships
Layer 4: Curriculum Engine    ─ Verified lesson assembly
Layer 5: Verification Engine  ─ Integrity & governance
```

Each layer is backed by a corresponding AI agent that automates the labour-intensive work of knowledge extraction, while humans retain final authority over what is verified and published.

---

## Data Flow

```
Document Upload
      │
      ▼
[Source Sentinel Agent]
  - Computes SHA-256 document hash
  - Registers source with trust tier
  - Extracts text into ExtractedText blocks
      │
      ▼
[Knowledge Cartographer Agent]
  - Splits text into sentences
  - Creates draft Claim records
  - Identifies concepts and relationships
  - Populates knowledge graph edges
      │
      ▼
[Human Verification Gate]
  - Domain experts review draft claims
  - Claims promoted to "verified" status
  - Contested or deprecated claims handled
      │
      ▼
[Curriculum Architect Agent]
  - Queries only verified claims
  - Groups claims into logical lessons
  - Builds module and course scaffolds
  - Generates quiz questions
  - Embeds [CLMxxxxxx] inline citations
      │
      ▼
[Integrity Auditor Agent]
  - Detects conflicts between claims
  - Flags outdated knowledge
  - Escalates high-confidence claims
  - Produces integrity reports
```

---

## Database Schema

### Sources
```
sources
├── source_id (PK, UUID)
├── title
├── publisher
├── edition
├── publication_date
├── document_hash (SHA-256, unique)
├── trust_tier (tier1/tier2/tier3)
├── license
├── source_url
├── file_path
├── page_count
├── word_count
├── language
├── is_active
├── metadata (JSON)
└── ingest_timestamp
```

### Claims
```
claims
├── claim_id (PK, UUID)
├── claim_number (CLMxxxxxx, unique)
├── concept_id (FK → concepts)
├── source_id (FK → sources)
├── statement (the knowledge statement)
├── citation_location
├── confidence_score (0.0–1.0)
├── status (draft/verified/contested/deprecated)
├── tags (JSON array)
├── version
└── created_at / updated_at
```

### Concepts & Relationships
```
concepts
├── concept_id (PK, UUID)
├── name (unique, lowercased)
├── description
├── domain
├── aliases (JSON array)
└── created_at

concept_relationships
├── relationship_id (PK, UUID)
├── parent_concept_id (FK)
├── child_concept_id (FK)
├── relationship_type (regulates/controls/contains/…)
├── weight
└── source_claim_id (FK, optional)
```

### Curriculum
```
courses → modules → lessons → lesson_claims
                           → quiz_questions
```

### Verification
```
claim_revisions    ─ Immutable history of every status change
verification_logs  ─ Every verification pass (AI and human)
conflict_flags     ─ Detected contradictions between claims
integrity_reports  ─ Audit run summaries
```

### Governance
```
agent_runs ─ Every AI agent execution with input/output/status
```

---

## Agent Architecture

### Agent 1 — Source Sentinel
**Input:** document file/bytes + metadata
**Output:** `source_id`, extracted text blocks
**Classifies trust tier** using publisher heuristics (configurable)

### Agent 2 — Knowledge Cartographer
**Input:** `source_id`
**Output:** draft claims + concept nodes + graph edges
**Uses** sentence-level extraction with relationship pattern matching

### Agent 3 — Curriculum Architect
**Input:** course definition + verified claim pool
**Output:** course with modules, lessons, and quiz questions
**Enforces** the no-hallucination invariant — only verified claims used

### Agent 4 — Integrity Auditor
**Input:** audit mode (full/conflicts_only/outdated_only/escalate)
**Output:** integrity report with flags and escalations
**Detects** contradictions using polarity-pair heuristics

---

## Governance Invariants (Enforced in Code)

1. **No unregistered sources** — Claims must reference a registered source
2. **No unverified claims in lessons** — `CurriculumBuilder.add_lesson()` raises if any claim is not `verified`
3. **No silent status transitions** — Every status change creates an immutable `ClaimRevision` record
4. **Human override always wins** — `GovernanceManager.human_override_claim()` bypasses AI assignments
5. **All agent runs are logged** — `AgentRun` records track every AI execution

---

## Extensibility

### Adding a new Academy Node
1. Create a new directory under `examples/`
2. Add source documents
3. Write a seed script using the existing agent pipeline
4. Pass your `academy_node` identifier when creating courses

### Adding a new Trust Tier
1. Add the enum value in `database/schemas/models.py`
2. Update the `SourceSentinelAgent._classify_tier()` heuristic
3. Run a database migration

### Replacing the Extraction Engine
The `KnowledgeCartographerAgent._run()` method is the only place that calls the extractor. Replace the sentence-splitting logic with an LLM call — the rest of the pipeline is unchanged.
