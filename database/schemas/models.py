"""
Universal Academy Engine — SQLAlchemy ORM Models
All database schemas for the UAE knowledge pipeline.
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean,
    DateTime, Enum, ForeignKey, JSON, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TrustTier(str, PyEnum):
    TIER1 = "tier1"   # Primary technical documentation
    TIER2 = "tier2"   # Accredited training sources
    TIER3 = "tier3"   # Supplemental sources


class ClaimStatus(str, PyEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    CONTESTED = "contested"
    DEPRECATED = "deprecated"


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


# ---------------------------------------------------------------------------
# Source Registry
# ---------------------------------------------------------------------------

class Source(Base):
    """Trusted knowledge source document."""
    __tablename__ = "sources"

    source_id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(String(512), nullable=False, index=True)
    publisher = Column(String(256), nullable=False)
    edition = Column(String(64), nullable=True)
    publication_date = Column(DateTime, nullable=True)
    document_hash = Column(String(64), nullable=False, unique=True, index=True)
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

    # Relationships
    claims = relationship("Claim", back_populates="source", cascade="all, delete-orphan")
    extracted_texts = relationship("ExtractedText", back_populates="source", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sources_trust_tier", "trust_tier"),
        Index("ix_sources_publisher", "publisher"),
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


# ---------------------------------------------------------------------------
# Concept & Knowledge Graph
# ---------------------------------------------------------------------------

class Concept(Base):
    """Named concept node in the knowledge graph."""
    __tablename__ = "concepts"

    concept_id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(256), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    aliases = Column(JSON, nullable=True)   # list of alternative names
    domain = Column(String(128), nullable=True, index=True)
    is_canonical = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
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
        "Concept",
        foreign_keys=[parent_concept_id],
        back_populates="parent_relationships",
    )
    child_concept = relationship(
        "Concept",
        foreign_keys=[child_concept_id],
        back_populates="child_relationships",
    )

    __table_args__ = (
        Index("ix_concept_rel_parent", "parent_concept_id"),
        Index("ix_concept_rel_child", "child_concept_id"),
    )


# ---------------------------------------------------------------------------
# Claim Ledger
# ---------------------------------------------------------------------------

class Claim(Base):
    """Atomic, source-attributed knowledge statement."""
    __tablename__ = "claims"

    claim_id = Column(String(36), primary_key=True, default=_uuid)
    concept_id = Column(String(36), ForeignKey("concepts.concept_id"), nullable=True, index=True)
    source_id = Column(String(36), ForeignKey("sources.source_id"), nullable=False, index=True)
    statement = Column(Text, nullable=False)
    citation_location = Column(String(256), nullable=True)   # e.g. "p.42, Section 3.2"
    confidence_score = Column(Float, nullable=False, default=0.5)
    status = Column(Enum(ClaimStatus), nullable=False, default=ClaimStatus.DRAFT, index=True)
    tags = Column(JSON, nullable=True)   # list of keyword tags
    claim_number = Column(String(32), nullable=True, unique=True, index=True)  # e.g. CLM001
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
    source = relationship("Source", back_populates="claims")
    concept = relationship("Concept", back_populates="claims")
    revisions = relationship("ClaimRevision", back_populates="claim", cascade="all, delete-orphan")
    verification_logs = relationship("VerificationLog", back_populates="claim", cascade="all, delete-orphan")
    lesson_claims = relationship("LessonClaim", back_populates="claim")

    __table_args__ = (
        Index("ix_claims_status_confidence", "status", "confidence_score"),
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
    timestamp = Column(DateTime, nullable=False, default=_now)

    claim = relationship("Claim", back_populates="revisions")


# ---------------------------------------------------------------------------
# Curriculum Engine
# ---------------------------------------------------------------------------

class Course(Base):
    """Top-level educational course."""
    __tablename__ = "courses"

    course_id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(String(512), nullable=False, index=True)
    academy_node = Column(String(128), nullable=False, index=True)
    description = Column(Text, nullable=True)
    version = Column(String(32), nullable=False, default="1.0")
    is_published = Column(Boolean, nullable=False, default=False)
    learning_objectives = Column(JSON, nullable=True)
    prerequisite_course_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    modules = relationship(
        "Module", back_populates="course",
        cascade="all, delete-orphan",
        order_by="Module.order",
    )

    def __repr__(self):
        return f"<Course(course_id={self.course_id!r}, title={self.title!r})>"


class Module(Base):
    """Ordered module within a course."""
    __tablename__ = "modules"

    module_id = Column(String(36), primary_key=True, default=_uuid)
    course_id = Column(String(36), ForeignKey("courses.course_id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, nullable=False, default=0)
    estimated_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    course = relationship("Course", back_populates="modules")
    lessons = relationship(
        "Lesson", back_populates="module",
        cascade="all, delete-orphan",
        order_by="Lesson.order",
    )


class Lesson(Base):
    """
    Individual lesson within a module.
    CONSTRAINT: every lesson MUST reference at least one verified claim.
    """
    __tablename__ = "lessons"

    lesson_id = Column(String(36), primary_key=True, default=_uuid)
    module_id = Column(String(36), ForeignKey("modules.module_id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    order = Column(Integer, nullable=False, default=0)
    estimated_minutes = Column(Integer, nullable=True)
    has_quiz = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    module = relationship("Module", back_populates="lessons")
    lesson_claims = relationship("LessonClaim", back_populates="lesson", cascade="all, delete-orphan")
    quiz_questions = relationship("QuizQuestion", back_populates="lesson", cascade="all, delete-orphan")


class LessonClaim(Base):
    """Many-to-many link between lessons and the claims they reference."""
    __tablename__ = "lesson_claims"

    id = Column(String(36), primary_key=True, default=_uuid)
    lesson_id = Column(String(36), ForeignKey("lessons.lesson_id"), nullable=False, index=True)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    inline_reference = Column(String(32), nullable=True)   # e.g. [CLM001]
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
    answer_options = Column(JSON, nullable=True)   # list of strings
    correct_answer = Column(String(512), nullable=False)
    explanation = Column(Text, nullable=True)
    difficulty = Column(String(32), nullable=False, default="medium")
    created_at = Column(DateTime, nullable=False, default=_now)

    lesson = relationship("Lesson", back_populates="quiz_questions")


# ---------------------------------------------------------------------------
# Verification Engine
# ---------------------------------------------------------------------------

class VerificationLog(Base):
    """Audit record for every claim verification action."""
    __tablename__ = "verification_logs"

    log_id = Column(String(36), primary_key=True, default=_uuid)
    claim_id = Column(String(36), ForeignKey("claims.claim_id"), nullable=False, index=True)
    verification_result = Column(String(64), nullable=False)   # pass / fail / needs_review
    reviewer = Column(String(256), nullable=True)   # human reviewer or agent name
    is_ai_review = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    review_status = Column(Enum(ReviewStatus), nullable=False, default=ReviewStatus.PENDING)
    timestamp = Column(DateTime, nullable=False, default=_now)

    claim = relationship("Claim", back_populates="verification_logs")


class IntegrityReport(Base):
    """Snapshot report from an Integrity Auditor run."""
    __tablename__ = "integrity_reports"

    report_id = Column(String(36), primary_key=True, default=_uuid)
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


# ---------------------------------------------------------------------------
# Agent Run Tracking
# ---------------------------------------------------------------------------

class AgentRun(Base):
    """Tracks every AI agent execution for audit and governance."""
    __tablename__ = "agent_runs"

    run_id = Column(String(36), primary_key=True, default=_uuid)
    agent_name = Column(String(128), nullable=False, index=True)
    input_payload = Column(JSON, nullable=True)
    output_summary = Column(JSON, nullable=True)
    status = Column(Enum(AgentRunStatus), nullable=False, default=AgentRunStatus.QUEUED)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
