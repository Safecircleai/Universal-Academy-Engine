# Architecture Suggestions

This document records proposed improvements to the UAE architecture.
Per governance guidelines, all architectural proposals must be documented here
before implementation.

---

## Suggestion 001 — LLM-Powered Claim Extraction (Priority: High)

**Status:** Proposed
**Author:** UAE Architecture Review

### Problem
The current `KnowledgeCartographerAgent` uses sentence-splitting heuristics and regex-based relationship detection. This approach:
- Misses implied relationships
- Cannot distinguish factual claims from procedural steps
- Cannot handle complex sentence structures

### Proposed Solution
Replace the heuristic extractor with a two-stage LLM pipeline:

**Stage 1 — Claim Identification**
Prompt the LLM with a text block and ask it to identify atomic factual claims, returning structured JSON.

**Stage 2 — Relationship Extraction**
Prompt the LLM with extracted claims and ask it to identify semantic relationships between concepts.

### Governance Notes
- LLM-extracted claims still enter as `draft` status
- Human verification gate is unchanged
- LLM must cite the exact text span it extracted each claim from
- Hallucinated claims (no source span) are rejected automatically

### Schema Changes Required
Add `source_span` (text offset) field to `claims` table.

---

## Suggestion 002 — Claim Similarity Index (Priority: Medium)

**Status:** Proposed
**Author:** UAE Architecture Review

### Problem
The current conflict detection uses simple polarity-word matching. Two semantically equivalent claims from different sources are not detected as duplicates, leading to redundant curriculum content.

### Proposed Solution
Build a vector embedding index of all verified claims using a sentence transformer model. Store embeddings in a dedicated column (or separate vector database). Use cosine similarity to:
- Detect near-duplicate claims (similarity > 0.92 → flag as duplicate)
- Find related claims for lesson grouping
- Power a semantic search endpoint

### Schema Changes Required
Add `embedding` (BLOB or vector type) field to `claims` table.
Add `GET /claims/similar/{claim_id}` endpoint.

---

## Suggestion 003 — Curriculum Diff & Versioning (Priority: Medium)

**Status:** Proposed
**Author:** UAE Architecture Review

### Problem
When claims are updated (e.g., due to regulatory changes), there is no automated mechanism to identify which lessons are affected and what changed.

### Proposed Solution
When a claim transitions from `verified` → `deprecated` (and is replaced by a new claim), the system should:
1. Identify all lessons that reference the deprecated claim
2. Generate a "curriculum diff" report
3. Notify course maintainers
4. Optionally auto-update lessons if the replacement claim is verified

### New Tables Required
- `curriculum_diffs` — records which lessons were affected by a claim change
- `course_subscriptions` — email/webhook endpoints for course change notifications

---

## Suggestion 004 — Multi-Language Support (Priority: Low)

**Status:** Proposed
**Author:** UAE Architecture Review

### Problem
The UAE currently only supports English-language sources. International vocational programs require Spanish, French, Portuguese, and other languages.

### Proposed Solution
- Add `language` field to claims (already exists on sources)
- Add language-aware claim extraction
- Enable curriculum generation in target language
- Claims in different languages for the same concept are linked via the knowledge graph

### Schema Changes Required
Add `language` field to `claims` table.
Add `translation_of_claim_id` FK to `claims` table for explicit translations.

---

## Suggestion 005 — Real-Time Pipeline API (Priority: Low)

**Status:** Proposed
**Author:** UAE Architecture Review

### Problem
The current pipeline is synchronous (request-response). For large documents (500+ pages), this causes API timeout issues.

### Proposed Solution
- Add a message queue (Redis or RabbitMQ) for agent tasks
- Convert agent endpoints to return a `task_id` immediately
- Add `GET /tasks/{task_id}` for polling
- Add WebSocket endpoint for real-time progress updates

### Infrastructure Changes Required
- Add Redis dependency
- Add `celery` or `arq` task queue
- Add `task_runs` table

---

*Last updated: 2024-03*
