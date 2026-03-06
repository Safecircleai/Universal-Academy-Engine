"""
Universal Academy Engine — SQLAlchemy ORM Models
Federation-hardened schema v2.0

New in v2:
  - AcademyNode + NodeGovernancePolicy (Part 1 — Federation)
  - ReviewerKey + VerificationAttestation (Part 2 — Cryptographic Verification)
  - ClaimEvidence (Part 3 — Evidence-Level Citations)
  - Extended PublishingState enum for Curriculum Lifecycle (Part 4)
  - Competency + Standard + CompetencyMapping (Part 5 — Standards Mapping)
  - Credential + CredentialCompetency (Part 6 — Credential Issuance)
  - Source storage hardening fields (Part 7)
  - AuditReport (Part 8 — Audit & Transparency)
  - All major entities now node-aware (origin_node_id / publishing_node_id)
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean,
    DateTime, Enum, ForeignKey, JSON, Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


# ===========================================================================
# Enumerations
# ===========================================================================

class TrustTier(str, PyEnum):
    TIER1 = "tier1"   # Primary technical documentation
    TIER2 = "tier2"   # Accredited training sources
    TIER3 = "tier3"   # Supplemental sources


class ClaimStatus(str, PyEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    CONTESTED = "contested"
    DEPRECATED = "deprecated"


class ClaimCategory(str, PyEnum):
    """Federation provenance category for a claim."""
    LOCAL = "local_claim"          # Originated in this node
    SHARED = "shared_claim"        # Published to the federation
    IMPORTED = "imported_claim"    # Adopted from another node
    CONTESTED = "contested_claim"  # Disputed across nodes


class RelationshipType(str, PyEnum):
    REGULATES = "regulates"
    CONTROLS = "controls"
    CONTAINS = "contains"
    REQUIRES = "requires"
    PRECEDES = "precedes"
    CAUSES = "causes"
    PART_OF = "part_of"
    RELATED_TO = "related_to"


class ReviewStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class AgentRunStatus(str, PyEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NodeType(str, PyEnum):
    VOCATIONAL_ACADEMY = "vocational_academy"
    CHARTER_SCHOOL = "charter_school"
    UNIVERSITY = "university"
    CERTIFICATION_BODY = "certification_body"
    COMMUNITY_EDUCATION = "community_education"
    GOVERNANCE_TRAINING = "governance_training"
    RESEARCH_INSTITUTION = "research_institution"


class PublishingState(str, PyEnum):
    """Full curriculum publishing lifecycle (Part 4)."""
    DRAFT = "draft"
    VERIFIED = "verified"       # All claims verified
    APPROVED = "approved"       # Human governance sign-off
    PUBLISHED = "published"     # Live for learners
    RESTRICTED = "restricted"   # Access-controlled
    DEPRECATED = "deprecated"   # No longer recommended
    SUPERSEDED = "superseded"   # Replaced by a newer version
    ARCHIVED = "archived"       # Preserved but not active


class SkillLevel(str, PyEnum):
    FOUNDATIONAL = "foundational"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class CredentialType(str, PyEnum):
    COMPLETION = "completion"
    COMPETENCY = "competency"
    CERTIFICATION = "certification"
    MASTERY = "mastery"


class StorageBackend(str, PyEnum):
    LOCAL = "local"
    IPFS = "ipfs"
    S3 = "s3"
    ARWEAVE = "arweave"


# ===========================================================================
# Part 1 — Federation: Academy Nodes
# ===========================================================================

class AcademyNode(Base):
    """
    A federated educational authority node.

    Each node is an independent actor in the UAE federation.
    Nodes publish claims, import claims from peers, and maintain
    their own governance policies.
    """
    __tablename__ = "academy_nodes"

    node_id = Column(String(36), primary_key=True, default=_uuid)
    node_name = Column(String(256), nullable=False, unique=True, index=True)
    node_type = Column(Enum(NodeType), nullable=False)
    description = Column(Text, nullable=True)
    contact_email = Column(String(256), nullable=True)
    website_url = Column(Text, nullable=True)
    # Public key for verifying signatures from this node
    public_key_pem = Column(Text, nullable=True)
    # DID or other decentralised identifier (future)
    did = Column(String(256), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_federation_member = Column(Boolean, nullable=False, default=False)
    joined_federation_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    governance_policy = relationship(
        "NodeGovernancePolicy", back_populates="node",
        uselist=False, cascade="all, delete-orphan"
    )
    reviewer_keys = relationship("ReviewerKey", back_populates="node")

    def __repr__(self):
        return f"<AcademyNode(node_id={self.node_id!r}, name={self.node_name!r})>"


class NodeGovernancePolicy(Base):
    """
    Per-node governance configuration (Part 9).

    Controls:
    - Minimum source trust tier accepted
    - Number and roles of required reviewers
    - Confidence threshold for auto-verification
    - Whether published courses require approval
    """
    __tablename__ = "node_governance_policies"

    policy_id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=False, unique=True)
    minimum_source_tier = Column(Enum(TrustTier), nullable=False, default=TrustTier.TIER3)
    required_reviewers = Column(Integer, nullable=False, default=1)
    reviewer_roles = Column(JSON, nullable=True)        # list of accepted role strings
    verification_threshold = Column(Float, nullable=False, default=0.75)
    require_approval_to_publish = Column(Boolean, nullable=False, default=True)
    allow_imported_claims = Column(Boolean, nullable=False, default=True)
    allow_claim_publication = Column(Boolean, nullable=False, default=False)
    auto_deprecate_after_days = Column(Integer, nullable=False, default=730)
    require_human_review_above_confidence = Column(Float, nullable=False, default=0.95)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    node = relationship("AcademyNode", back_populates="governance_policy")


# ===========================================================================
# Part 2 — Cryptographic Verification: Reviewer Keys & Attestations
# ===========================================================================

class ReviewerKey(Base):
    """
    Public key record for a human reviewer.

    Reviewers sign their verification decisions with their private key.
    The corresponding public key is stored here so signatures can be
    independently verified.
    """
    __tablename__ = "reviewer_keys"

    key_id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=False, index=True)
    reviewer_id = Column(String(256), nullable=False, index=True)
    reviewer_name = Column(String(256), nullable=True)
    reviewer_role = Column(String(128), nullable=True)
    reviewer_credentials = Column(JSON, nullable=True)   # certifications, qualifications
    public_key_pem = Column(Text, nullable=False)
    key_fingerprint = Column(String(128), nullable=False, unique=True)
    signature_algorithm = Column(String(64), nullable=False, default="RSA-SHA256")
    is_active = Column(Boolean, nullable=False, default=True)
    valid_from = Column(DateTime, nullable=False, default=_now)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    node = relationship("AcademyNode", back_populates="reviewer_keys")
    attestations = relationship("VerificationAttestation", back_populates="reviewer_key")

    __table_args__ = (
        Index("ix_reviewer_keys_node_reviewer", "node_id", "reviewer_id"),
    )


class VerificationAttestation(Base):
    """
    Cryptographically signed verification record (Part 2).

    Each human verification produces an attestation that can be
    independently verified using the reviewer's public key.
    This transforms "recorded" into "provable".

    Fields:
      claim_hash        — SHA-256 of the claim statement at time of signing
      reviewer_signature — Base64-encoded signature over (claim_hash + timestamp)
      signature_algorithm — Algorithm used (RSA-SHA256, Ed25519, etc.)
    """
    __tablename__ = "verification_attestations"

    attestation_id = Column(String(36), primary_key=True, default=_uuid)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    log_id = Column(String(36), ForeignKey("verification_logs.log_id"), nullable=True, index=True)
    reviewer_key_id = Column(String(36), ForeignKey("reviewer_keys.key_id"), nullable=False)

    # Cryptographic fields
    claim_hash = Column(String(128), nullable=False)       # SHA-256 of claim statement
    reviewer_signature = Column(Text, nullable=False)       # Base64-encoded signature
    signature_algorithm = Column(String(64), nullable=False, default="RSA-SHA256")
    signed_payload = Column(Text, nullable=True)           # canonical JSON that was signed

    # Human-readable context
    reviewer_id = Column(String(256), nullable=False)
    reviewer_role = Column(String(128), nullable=True)
    verification_reason = Column(Text, nullable=True)
    verification_timestamp = Column(DateTime, nullable=False, default=_now)

    # Verification status
    signature_verified = Column(Boolean, nullable=True)    # result of local sig check
    verified_at = Column(DateTime, nullable=True)

    reviewer_key = relationship("ReviewerKey", back_populates="attestations")

    __table_args__ = (
        Index("ix_attestation_claim", "claim_id"),
        Index("ix_attestation_reviewer", "reviewer_id"),
    )


# ===========================================================================
# Part 7 — Source Registry (hardened)
# ===========================================================================

class Source(Base):
    """
    Trusted knowledge source document — hardened for federation.

    New fields:
      origin_node_id    — node that registered the source
      content_address   — content-addressable identifier (e.g., IPFS CID)
      document_fingerprint — secondary fingerprint (e.g., BLAKE3)
      storage_backend   — where the original file is stored
    """
    __tablename__ = "sources"

    source_id = Column(String(36), primary_key=True, default=_uuid)
    # Federation
    origin_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    # Core fields
    title = Column(String(512), nullable=False, index=True)
    publisher = Column(String(256), nullable=False)
    edition = Column(String(64), nullable=True)
    publication_date = Column(DateTime, nullable=True)
    # Storage hardening (Part 7)
    document_hash = Column(String(128), nullable=False, unique=True, index=True)  # SHA-256
    document_fingerprint = Column(String(128), nullable=True)   # BLAKE3 or SHA-3 secondary hash
    content_address = Column(String(256), nullable=True)         # IPFS CID / Arweave TX
    storage_backend = Column(Enum(StorageBackend), nullable=False, default=StorageBackend.LOCAL)
    # Metadata
    trust_tier = Column(Enum(TrustTier), nullable=False, default=TrustTier.TIER3)
    license = Column(String(256), nullable=True)
    source_url = Column(Text, nullable=True)
    file_path = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    word_count = Column(Integer, nullable=True)
    language = Column(String(16), nullable=False, default="en")
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    ingest_timestamp = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    origin_node = relationship("AcademyNode", foreign_keys=[origin_node_id])
    claims = relationship("Claim", back_populates="source", cascade="all, delete-orphan")
    extracted_texts = relationship("ExtractedText", back_populates="source", cascade="all, delete-orphan")
    evidences = relationship("ClaimEvidence", back_populates="source")

    __table_args__ = (
        Index("ix_sources_trust_tier", "trust_tier"),
        Index("ix_sources_publisher", "publisher"),
        Index("ix_sources_origin_node", "origin_node_id"),
    )

    def __repr__(self):
        return f"<Source(source_id={self.source_id!r}, title={self.title!r})>"


class ExtractedText(Base):
    """Raw extracted text blocks from source documents."""
    __tablename__ = "extracted_texts"

    text_id = Column(String(36), primary_key=True, default=_uuid)
    source_id = Column(String(36), ForeignKey("sources.source_id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=True)
    section_title = Column(String(512), nullable=True)
    content = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=True)
    extraction_method = Column(String(64), nullable=True)
    extracted_at = Column(DateTime, nullable=False, default=_now)

    source = relationship("Source", back_populates="extracted_texts")


# ===========================================================================
# Part 3 — Evidence-Level Citations
# ===========================================================================

class ClaimEvidence(Base):
    """
    Granular evidence reference for a claim (Part 3).

    Allows audits to trace a claim to an exact fragment of a source document:
    page, section, paragraph, figure, or time-coded segment.
    """
    __tablename__ = "claim_evidences"

    evidence_id = Column(String(36), primary_key=True, default=_uuid)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("sources.source_id"), nullable=False, index=True)

    # Location within source
    page_range = Column(String(32), nullable=True)        # e.g. "42-43"
    section = Column(String(256), nullable=True)           # section heading
    paragraph = Column(Integer, nullable=True)             # paragraph number
    figure_reference = Column(String(128), nullable=True)  # e.g. "Figure 3.2"
    timecode = Column(String(32), nullable=True)           # e.g. "01:23:45" for video

    # Exact evidence content
    exact_quote = Column(Text, nullable=True)              # verbatim text
    extracted_text = Column(Text, nullable=True)           # AI-extracted paraphrase
    diagram_reference = Column(String(256), nullable=True) # diagram label/caption
    evidence_text_hash = Column(String(128), nullable=True) # SHA-256 of exact_quote

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    claim = relationship("Claim", back_populates="evidences")
    source = relationship("Source", back_populates="evidences")


# ===========================================================================
# Concept & Knowledge Graph (node-aware)
# ===========================================================================

class Concept(Base):
    """Named concept node in the knowledge graph — now federation-aware."""
    __tablename__ = "concepts"

    concept_id = Column(String(36), primary_key=True, default=_uuid)
    # Federation
    origin_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    # Core fields
    name = Column(String(256), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    aliases = Column(JSON, nullable=True)
    domain = Column(String(128), nullable=True, index=True)
    is_canonical = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    origin_node = relationship("AcademyNode", foreign_keys=[origin_node_id])
    claims = relationship("Claim", back_populates="concept")
    parent_relationships = relationship(
        "ConceptRelationship",
        foreign_keys="ConceptRelationship.parent_concept_id",
        back_populates="parent_concept",
        cascade="all, delete-orphan",
    )
    child_relationships = relationship(
        "ConceptRelationship",
        foreign_keys="ConceptRelationship.child_concept_id",
        back_populates="child_concept",
        cascade="all, delete-orphan",
    )
    competency_mappings = relationship("CompetencyMapping", back_populates="concept")

    def __repr__(self):
        return f"<Concept(concept_id={self.concept_id!r}, name={self.name!r})>"


class ConceptRelationship(Base):
    """Directed edge in the knowledge graph."""
    __tablename__ = "concept_relationships"

    relationship_id = Column(String(36), primary_key=True, default=_uuid)
    parent_concept_id = Column(String(36), ForeignKey("concepts.concept_id"), nullable=False)
    child_concept_id = Column(String(36), ForeignKey("concepts.concept_id"), nullable=False)
    relationship_type = Column(Enum(RelationshipType), nullable=False)
    weight = Column(Float, nullable=False, default=1.0)
    source_claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    parent_concept = relationship(
        "Concept", foreign_keys=[parent_concept_id], back_populates="parent_relationships"
    )
    child_concept = relationship(
        "Concept", foreign_keys=[child_concept_id], back_populates="child_relationships"
    )

    __table_args__ = (
        Index("ix_concept_rel_parent", "parent_concept_id"),
        Index("ix_concept_rel_child", "child_concept_id"),
    )


# ===========================================================================
# Claim Ledger (federation-hardened)
# ===========================================================================

class Claim(Base):
    """
    Atomic, source-attributed knowledge statement — federation-hardened.

    New fields:
      origin_node_id      — node where this claim was first created
      publishing_node_id  — node that published it to the federation
      claim_category      — local / shared / imported / contested
      claim_hash          — SHA-256 of the canonical claim statement
      superseded_by_id    — FK to the replacement claim
    """
    __tablename__ = "claims"

    claim_id = Column(String(36), primary_key=True, default=_uuid)
    # Federation
    origin_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    publishing_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    claim_category = Column(Enum(ClaimCategory), nullable=False, default=ClaimCategory.LOCAL)
    # Core fields
    concept_id = Column(String(36), ForeignKey("concepts.concept_id"), nullable=True, index=True)
    source_id = Column(String(36), ForeignKey("sources.source_id"), nullable=False, index=True)
    statement = Column(Text, nullable=False)
    citation_location = Column(String(256), nullable=True)
    confidence_score = Column(Float, nullable=False, default=0.5)
    status = Column(Enum(ClaimStatus), nullable=False, default=ClaimStatus.DRAFT, index=True)
    tags = Column(JSON, nullable=True)
    claim_number = Column(String(32), nullable=True, unique=True, index=True)
    # Provenance hardening
    claim_hash = Column(String(128), nullable=True, index=True)  # SHA-256 of statement
    version = Column(Integer, nullable=False, default=1)
    superseded_by_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    origin_node = relationship("AcademyNode", foreign_keys=[origin_node_id])
    publishing_node = relationship("AcademyNode", foreign_keys=[publishing_node_id])
    source = relationship("Source", back_populates="claims")
    concept = relationship("Concept", back_populates="claims")
    revisions = relationship("ClaimRevision", back_populates="claim", cascade="all, delete-orphan")
    verification_logs = relationship("VerificationLog", back_populates="claim", cascade="all, delete-orphan")
    attestations = relationship("VerificationAttestation", back_populates="claim")
    lesson_claims = relationship("LessonClaim", back_populates="claim")
    evidences = relationship("ClaimEvidence", back_populates="claim", cascade="all, delete-orphan")
    competency_mappings = relationship("CompetencyMapping", back_populates="claim")
    superseded_by = relationship("Claim", remote_side="Claim.claim_id", foreign_keys=[superseded_by_id])

    __table_args__ = (
        Index("ix_claims_status_confidence", "status", "confidence_score"),
        Index("ix_claims_origin_node", "origin_node_id"),
        Index("ix_claims_category", "claim_category"),
    )

    def __repr__(self):
        return f"<Claim(claim_id={self.claim_id!r}, number={self.claim_number!r})>"


class ClaimRevision(Base):
    """Immutable revision history for a claim."""
    __tablename__ = "claim_revisions"

    revision_id = Column(String(36), primary_key=True, default=_uuid)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    previous_version = Column(Text, nullable=False)
    updated_version = Column(Text, nullable=False)
    change_reason = Column(Text, nullable=True)
    changed_by = Column(String(256), nullable=True)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=_now)

    claim = relationship("Claim", back_populates="revisions")


# ===========================================================================
# Part 1 — Claim Federation Protocol
# ===========================================================================

class FederatedClaimRecord(Base):
    """
    Tracks cross-node claim sharing events.

    When a node publishes a claim to the federation, or imports a claim
    from another node, a record is created here.  This enables provenance
    tracing across the entire federation.
    """
    __tablename__ = "federated_claim_records"

    record_id = Column(String(36), primary_key=True, default=_uuid)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    action = Column(String(64), nullable=False)       # publish / import / contest / adopt
    source_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=False)
    target_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True)
    notes = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)             # full claim snapshot at time of action
    timestamp = Column(DateTime, nullable=False, default=_now)

    source_node = relationship("AcademyNode", foreign_keys=[source_node_id])
    target_node = relationship("AcademyNode", foreign_keys=[target_node_id])

    __table_args__ = (
        Index("ix_fed_claim_record_claim", "claim_id"),
        Index("ix_fed_claim_record_action", "action"),
    )


# ===========================================================================
# Part 4 — Curriculum Engine (extended publishing lifecycle)
# ===========================================================================

class Course(Base):
    """
    Top-level educational course — extended publishing lifecycle.

    Publishing states: draft → verified → approved → published
    Supersession: superseded_by_id points to the replacement.
    """
    __tablename__ = "courses"

    course_id = Column(String(36), primary_key=True, default=_uuid)
    # Federation
    origin_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    # Core fields
    title = Column(String(512), nullable=False, index=True)
    academy_node = Column(String(128), nullable=False, index=True)   # human-readable label kept for compat
    description = Column(Text, nullable=True)
    version = Column(String(32), nullable=False, default="1.0")
    # Extended publishing lifecycle
    publishing_state = Column(
        Enum(PublishingState), nullable=False,
        default=PublishingState.DRAFT, index=True
    )
    is_published = Column(Boolean, nullable=False, default=False)    # kept for compat
    approved_by = Column(String(256), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    restricted_reason = Column(Text, nullable=True)
    superseded_by_id = Column(String(36), ForeignKey("courses.course_id"), nullable=True)
    # Metadata
    learning_objectives = Column(JSON, nullable=True)
    prerequisite_course_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    origin_node = relationship("AcademyNode", foreign_keys=[origin_node_id])
    superseded_by = relationship("Course", remote_side="Course.course_id", foreign_keys=[superseded_by_id])
    modules = relationship(
        "Module", back_populates="course",
        cascade="all, delete-orphan", order_by="Module.order",
    )
    competency_mappings = relationship("CompetencyMapping", back_populates="course")

    def __repr__(self):
        return f"<Course(course_id={self.course_id!r}, title={self.title!r})>"


class Module(Base):
    """Ordered module within a course — node-aware."""
    __tablename__ = "modules"

    module_id = Column(String(36), primary_key=True, default=_uuid)
    course_id = Column(String(36), ForeignKey("courses.course_id"), nullable=False, index=True)
    origin_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, nullable=False, default=0)
    estimated_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    course = relationship("Course", back_populates="modules")
    lessons = relationship(
        "Lesson", back_populates="module",
        cascade="all, delete-orphan", order_by="Lesson.order",
    )


class Lesson(Base):
    """
    Individual lesson — extended publishing lifecycle.

    Governance invariants (enforced by CurriculumBuilder):
      - MUST reference at least one verified claim.
      - Draft / deprecated claims cannot be referenced.
      - Superseded claims must reference their replacement.
      - Publishing requires human approval when node policy demands it.
    """
    __tablename__ = "lessons"

    lesson_id = Column(String(36), primary_key=True, default=_uuid)
    module_id = Column(String(36), ForeignKey("modules.module_id"), nullable=False, index=True)
    origin_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    order = Column(Integer, nullable=False, default=0)
    estimated_minutes = Column(Integer, nullable=True)
    has_quiz = Column(Boolean, nullable=False, default=False)
    # Extended lifecycle
    publishing_state = Column(
        Enum(PublishingState), nullable=False,
        default=PublishingState.DRAFT, index=True
    )
    approved_by = Column(String(256), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    superseded_by_id = Column(String(36), ForeignKey("lessons.lesson_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    module = relationship("Module", back_populates="lessons")
    superseded_by = relationship("Lesson", remote_side="Lesson.lesson_id", foreign_keys=[superseded_by_id])
    lesson_claims = relationship("LessonClaim", back_populates="lesson", cascade="all, delete-orphan")
    quiz_questions = relationship("QuizQuestion", back_populates="lesson", cascade="all, delete-orphan")
    competency_mappings = relationship("CompetencyMapping", back_populates="lesson")


class LessonClaim(Base):
    """Many-to-many link between lessons and the claims they reference."""
    __tablename__ = "lesson_claims"

    id = Column(String(36), primary_key=True, default=_uuid)
    lesson_id = Column(String(36), ForeignKey("lessons.lesson_id"), nullable=False, index=True)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    inline_reference = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    lesson = relationship("Lesson", back_populates="lesson_claims")
    claim = relationship("Claim", back_populates="lesson_claims")


class QuizQuestion(Base):
    """Quiz question attached to a lesson, derived from claims."""
    __tablename__ = "quiz_questions"

    question_id = Column(String(36), primary_key=True, default=_uuid)
    lesson_id = Column(String(36), ForeignKey("lessons.lesson_id"), nullable=False, index=True)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=True)
    question_text = Column(Text, nullable=False)
    answer_options = Column(JSON, nullable=True)
    correct_answer = Column(String(512), nullable=False)
    explanation = Column(Text, nullable=True)
    difficulty = Column(String(32), nullable=False, default="medium")
    created_at = Column(DateTime, nullable=False, default=_now)

    lesson = relationship("Lesson", back_populates="quiz_questions")


# ===========================================================================
# Verification Engine (node-aware)
# ===========================================================================

class VerificationLog(Base):
    """Audit record for every claim verification action — now attestation-linked."""
    __tablename__ = "verification_logs"

    log_id = Column(String(36), primary_key=True, default=_uuid)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    verification_result = Column(String(64), nullable=False)
    reviewer = Column(String(256), nullable=True)
    is_ai_review = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    review_status = Column(Enum(ReviewStatus), nullable=False, default=ReviewStatus.PENDING)
    timestamp = Column(DateTime, nullable=False, default=_now)

    claim = relationship("Claim", back_populates="verification_logs")
    attestation = relationship(
        "VerificationAttestation", back_populates="log",
        primaryjoin="VerificationLog.log_id == foreign(VerificationAttestation.log_id)",
        uselist=False,
    )


# Patch VerificationAttestation to add back-reference
VerificationAttestation.claim = relationship("Claim", back_populates="attestations")
VerificationAttestation.log = relationship(
    "VerificationLog",
    primaryjoin="VerificationAttestation.log_id == foreign(VerificationLog.log_id)",
    back_populates="attestation",
    uselist=False,
)


class IntegrityReport(Base):
    """Snapshot report from an Integrity Auditor run."""
    __tablename__ = "integrity_reports"

    report_id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    run_by = Column(String(256), nullable=False, default="integrity_auditor_agent")
    total_claims_checked = Column(Integer, nullable=False, default=0)
    conflicts_found = Column(Integer, nullable=False, default=0)
    outdated_claims = Column(Integer, nullable=False, default=0)
    flagged_for_review = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)


class ConflictFlag(Base):
    """Records a detected conflict between two claims."""
    __tablename__ = "conflict_flags"

    flag_id = Column(String(36), primary_key=True, default=_uuid)
    claim_a_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False)
    claim_b_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False)
    conflict_description = Column(Text, nullable=False)
    resolution_status = Column(String(64), nullable=False, default="unresolved")
    resolved_by = Column(String(256), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_conflict_flag_claim_a", "claim_a_id"),
        Index("ix_conflict_flag_claim_b", "claim_b_id"),
    )


# ===========================================================================
# Part 5 — Competency & Standards Mapping
# ===========================================================================

class Competency(Base):
    """
    A skill or competency that curriculum can develop (Part 5).

    Competencies link claims and lessons to workforce / academic standards.
    """
    __tablename__ = "competencies"

    competency_id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    code = Column(String(64), nullable=True, index=True)           # e.g. NATEF-T002.1
    name = Column(String(256), nullable=False, index=True)
    description = Column(Text, nullable=True)
    skill_level = Column(Enum(SkillLevel), nullable=False, default=SkillLevel.FOUNDATIONAL)
    domain = Column(String(128), nullable=True, index=True)
    industry_standard_reference = Column(String(256), nullable=True)  # e.g. "ASE A1.3"
    standard_id = Column(String(36), ForeignKey("standards.standard_id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    standard = relationship("Standard", back_populates="competencies")
    mappings = relationship("CompetencyMapping", back_populates="competency")
    credential_competencies = relationship("CredentialCompetency", back_populates="competency")


class Standard(Base):
    """
    An external educational or industry standard (Part 5).

    Examples: NATEF, Common Core, ASE, CompTIA, ISO 9001.
    """
    __tablename__ = "standards"

    standard_id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(256), nullable=False, unique=True, index=True)
    issuing_body = Column(String(256), nullable=False)
    version = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    domain = Column(String(128), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    competencies = relationship("Competency", back_populates="standard")


class CompetencyMapping(Base):
    """
    Links claims, lessons, and courses to competencies (Part 5).

    Enables curriculum audits like:
      "Which competencies does this course address?"
      "Which claims support this NATEF task?"
    """
    __tablename__ = "competency_mappings"

    mapping_id = Column(String(36), primary_key=True, default=_uuid)
    competency_id = Column(String(36), ForeignKey("competencies.competency_id"), nullable=False, index=True)
    # Exactly one of the following must be set
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=True, index=True)
    lesson_id = Column(String(36), ForeignKey("lessons.lesson_id"), nullable=True, index=True)
    course_id = Column(String(36), ForeignKey("courses.course_id"), nullable=True, index=True)
    concept_id = Column(String(36), ForeignKey("concepts.concept_id"), nullable=True, index=True)
    alignment_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    competency = relationship("Competency", back_populates="mappings")
    claim = relationship("Claim", back_populates="competency_mappings")
    lesson = relationship("Lesson", back_populates="competency_mappings")
    course = relationship("Course", back_populates="competency_mappings")
    concept = relationship("Concept", back_populates="competency_mappings")


# ===========================================================================
# Part 6 — Credential Issuance
# ===========================================================================

class Credential(Base):
    """
    Verifiable credential issued upon course completion (Part 6).

    Exportable as: JSON credential, signed certificate, portable token.
    Designed for W3C Verifiable Credentials compatibility.
    """
    __tablename__ = "credentials"

    credential_id = Column(String(36), primary_key=True, default=_uuid)
    # Learner identity
    student_id = Column(String(256), nullable=False, index=True)
    student_name = Column(String(256), nullable=True)
    student_email = Column(String(256), nullable=True)
    # What was completed
    course_id = Column(String(36), ForeignKey("courses.course_id"), nullable=False, index=True)
    # Issuing authority
    issuing_node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=False, index=True)
    issued_by = Column(String(256), nullable=False)       # reviewer/admin who issued
    credential_type = Column(Enum(CredentialType), nullable=False, default=CredentialType.COMPLETION)
    # Cryptographic proof
    verification_signature = Column(Text, nullable=True)   # Base64 signature
    signature_algorithm = Column(String(64), nullable=True, default="RSA-SHA256")
    credential_hash = Column(String(128), nullable=True)   # SHA-256 of canonical credential JSON
    # Lifecycle
    issue_date = Column(DateTime, nullable=False, default=_now)
    expiry_date = Column(DateTime, nullable=True)
    is_revoked = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, nullable=True)
    # W3C VC compatible fields
    context = Column(JSON, nullable=True)                 # @context
    credential_subject = Column(JSON, nullable=True)      # credentialSubject
    proof = Column(JSON, nullable=True)                   # proof block

    course = relationship("Course", foreign_keys=[course_id])
    issuing_node = relationship("AcademyNode", foreign_keys=[issuing_node_id])
    competencies = relationship("CredentialCompetency", back_populates="credential", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_credential_student", "student_id"),
        Index("ix_credential_course", "course_id"),
    )

    def __repr__(self):
        return f"<Credential(credential_id={self.credential_id!r}, student={self.student_id!r})>"


class CredentialCompetency(Base):
    """Competencies demonstrated by a credential holder."""
    __tablename__ = "credential_competencies"

    id = Column(String(36), primary_key=True, default=_uuid)
    credential_id = Column(String(36), ForeignKey("credentials.credential_id"), nullable=False, index=True)
    competency_id = Column(String(36), ForeignKey("competencies.competency_id"), nullable=False, index=True)
    mastery_score = Column(Float, nullable=True)          # 0.0–1.0
    evidence_notes = Column(Text, nullable=True)

    credential = relationship("Credential", back_populates="competencies")
    competency = relationship("Competency", back_populates="credential_competencies")


# ===========================================================================
# Part 8 — Audit & Transparency
# ===========================================================================

class AuditReport(Base):
    """
    Exportable audit report (Part 8).

    Answers: who verified, from which source, when was it changed,
    what replaced it, which courses depend on it.
    """
    __tablename__ = "audit_reports"

    audit_id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    report_type = Column(String(64), nullable=False, index=True)  # claim / course / node / full
    subject_id = Column(String(36), nullable=True, index=True)    # claim_id, course_id, etc.
    generated_by = Column(String(256), nullable=False)
    # Report content
    summary = Column(Text, nullable=True)
    findings = Column(JSON, nullable=True)
    recommendations = Column(JSON, nullable=True)
    raw_data = Column(JSON, nullable=True)
    # Exportable flag
    is_exportable = Column(Boolean, nullable=False, default=True)
    export_format = Column(String(32), nullable=True)     # json / pdf / csv
    created_at = Column(DateTime, nullable=False, default=_now)


# ===========================================================================
# Agent Run Tracking
# ===========================================================================

class AgentRun(Base):
    """Tracks every AI agent execution for audit and governance."""
    __tablename__ = "agent_runs"

    run_id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("academy_nodes.node_id"), nullable=True, index=True)
    agent_name = Column(String(128), nullable=False, index=True)
    input_payload = Column(JSON, nullable=True)
    output_summary = Column(JSON, nullable=True)
    status = Column(Enum(AgentRunStatus), nullable=False, default=AgentRunStatus.QUEUED)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
