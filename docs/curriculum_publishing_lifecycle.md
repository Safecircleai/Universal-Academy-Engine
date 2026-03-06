# Curriculum Publishing Lifecycle

## Overview

Courses and lessons in the UAE follow a structured publishing lifecycle. Each state represents a distinct governance checkpoint, ensuring that educational content is verified, approved, and traceable before reaching learners.

The lifecycle is enforced by the `CurriculumBuilder` in `core/curriculum_engine/curriculum_builder.py` and backed by the `PublishingState` enum in `database/schemas/models.py`.

---

## State Machine

```
DRAFT
  │
  │  (internal editing)
  ▼
VERIFIED ─────────────────────────────────────────────────────┐
  │                                                            │
  │  approve_course()                                         │
  ▼                                                            │
APPROVED                                                       │
  │                                                            │
  │  publish_course()                                         │
  ▼                                                            │
PUBLISHED ───────────────────────────────────────────────────┐ │
  │              │                                            │ │
  │  restrict()  │  supersede_course()                       │ │
  ▼              ▼                                            │ │
RESTRICTED   SUPERSEDED                                       │ │
  │                                                           │ │
  │  deprecate_course()                                       │ │
  ▼                                                           │ │
DEPRECATED ──────────────────────────────────────────────────┘ │
  │                                                             │
  │  archive_course()                                           │
  ▼                                                             │
ARCHIVED ◄────────────────────────────────────────────────────-┘
```

---

## States

### `DRAFT`

**Entry:** All courses start in `DRAFT` state when created via `create_course()`.

**Characteristics:**
- Content is editable — modules, lessons, and claim assignments can be changed
- Not visible to learners
- No governance approvals required

**Allowed operations:** `add_module()`, `add_lesson()`, `approve_course()`, `deprecate_course()`

---

### `VERIFIED`

**Entry:** Not directly set via the builder. Represents courses whose source claims have all been verified but the course itself has not been formally approved.

**Characteristics:**
- All lesson claim_ids must point to `ClaimStatus.VERIFIED` claims (enforced by `add_lesson()`)
- The no-hallucination invariant is satisfied: every fact in the course traces to a verified, sourced claim

---

### `APPROVED`

**Entry:** `approve_course(course_id, approved_by)`

**Characteristics:**
- A named human reviewer has signed off on the course
- `approved_by` and `approved_at` are recorded
- Course is ready for publication but not yet live

**Allowed next state:** `PUBLISHED`

---

### `PUBLISHED`

**Entry:** `publish_course(course_id)`

**Characteristics:**
- Course is live and credentials may be issued to students
- `published_at` timestamp is recorded
- `CredentialIssuer.issue_credential()` requires `PUBLISHED` or `RESTRICTED` state

**Allowed next states:** `RESTRICTED`, `SUPERSEDED`, `DEPRECATED`

---

### `RESTRICTED`

**Entry:** Restricted state allows a course to remain technically active for enrolled students while being hidden from new enrollment.

**Characteristics:**
- Credentials can still be issued for existing enrollments
- New enrollments are blocked at the application layer

**Allowed next states:** `DEPRECATED`, `ARCHIVED`

---

### `SUPERSEDED`

**Entry:** `supersede_course(course_id, superseded_by_id)`

**Characteristics:**
- `superseded_by_id` points to the replacement course
- The old course is retained for audit and backward compatibility
- Credentials issued under the old course remain valid unless explicitly revoked

**Allowed next state:** `ARCHIVED`

---

### `DEPRECATED`

**Entry:** `deprecate_course(course_id)`

**Characteristics:**
- Course is no longer recommended but is retained in the system
- No new credentials may be issued
- Historical audit access is preserved

**Allowed next state:** `ARCHIVED`

---

### `ARCHIVED`

**Entry:** `archive_course(course_id)`

**Characteristics:**
- Terminal state — no transitions out of ARCHIVED
- Content is immutable
- Full audit trail is preserved indefinitely

---

## The No-Hallucination Invariant

The most critical governance invariant in the curriculum engine:

> **Every claim cited in a lesson must be in `ClaimStatus.VERIFIED` state at the time the lesson is written.**

This is enforced in `CurriculumBuilder.add_lesson()`:

```python
for claim_id in claim_ids:
    claim = await self._get_verified_claim(claim_id)
    # Raises CurriculumBuilderError if claim is DRAFT, DEPRECATED, or CONFLICTED
```

If a claim is later deprecated or conflicted:
- Existing lessons retain the reference in `LessonClaim`
- The `IntegrityAuditorAgent` will flag the lesson in its next audit pass
- The course must be updated and re-published through the full lifecycle

---

## Lesson Publishing States

Lessons carry their own `publishing_state` (inherited from the parent course at publication time):

- Lessons in `DRAFT` courses are in `DRAFT`
- Lessons in `PUBLISHED` courses are in `PUBLISHED`
- Individual lesson states can be updated independently for granular control

---

## Credential Issuance Gate

`CredentialIssuer.issue_credential()` enforces:

```python
if course.publishing_state not in (PublishingState.PUBLISHED, PublishingState.RESTRICTED):
    raise CredentialError(
        f"Credentials can only be issued for published courses."
    )
```

This ensures students only receive credentials for courses that have passed the full governance pipeline.

---

## Audit Trail

Every state transition is captured in the audit report produced by `AuditManager.audit_course()`:

- `publishing_state` — current state
- `approved_by` / `approved_at` — approval chain
- `published_at` — publication timestamp
- `superseded_by_id` — supersession chain
- Module and lesson states with claim citation counts

---

## Example Lifecycle (CFRS Academy Fleet Maintenance Course)

```
1. CurriculumBuilder.create_course("Fleet Maintenance Fundamentals")
   → DRAFT

2. Instructors add modules, lessons, and verified claim citations

3. CurriculumBuilder.approve_course(course_id, approved_by="head_instructor")
   → APPROVED

4. CurriculumBuilder.publish_course(course_id)
   → PUBLISHED  (credentials can now be issued)

5. FMCSA updates regulations. New source ingested, new claims verified.

6. CurriculumBuilder.create_course("Fleet Maintenance Fundamentals v2")
   → DRAFT (new course)

7. CurriculumBuilder.supersede_course(old_course_id, superseded_by_id=new_course_id)
   → SUPERSEDED (old course)

8. New course follows full lifecycle → PUBLISHED

9. Old course archived:
   CurriculumBuilder.archive_course(old_course_id)
   → ARCHIVED
```
