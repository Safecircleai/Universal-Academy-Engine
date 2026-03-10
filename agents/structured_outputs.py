"""
UAE v3 — Structured Agent Outputs

All agent LLM outputs MUST be validated against these Pydantic schemas
before being routed downstream.

Invariant: No LLM output directly becomes a verified claim or curriculum element.
All outputs pass through governance review. Agents produce PROPOSALS, not facts.

Validation flow:
  LLM output (raw JSON string)
    → parse_agent_output(raw, schema)
    → validated Pydantic model
    → passed to governance manager for human review routing
    → NOT written directly to claims/courses without review_status = APPROVED
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class AgentOutputError(Exception):
    """Raised when an agent output fails schema validation."""


# ------------------------------------------------------------------
# Source Sentinel Outputs
# ------------------------------------------------------------------

class SourceValidationOutput(BaseModel):
    """Output from Source Sentinel validation run."""
    source_id: str
    is_valid: bool
    trust_tier: str
    validation_notes: str
    detected_language: str = "en"
    estimated_page_count: Optional[int] = None
    requires_human_review: bool = True

    @field_validator("trust_tier")
    @classmethod
    def valid_tier(cls, v: str) -> str:
        if v not in ("TIER1", "TIER2", "TIER3"):
            raise ValueError(f"Invalid trust_tier: {v!r}")
        return v


# ------------------------------------------------------------------
# Knowledge Cartographer Outputs
# ------------------------------------------------------------------

class ProposedClaim(BaseModel):
    """A claim proposed by the Knowledge Cartographer. NOT yet verified."""
    statement: str = Field(min_length=10, max_length=2000)
    source_id: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    concept_name: Optional[str] = None
    page_range: Optional[str] = None
    supporting_quote: Optional[str] = None
    requires_human_review: bool = True

    @field_validator("statement")
    @classmethod
    def no_empty_statement(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Claim statement cannot be empty or whitespace.")
        return v.strip()


class KnowledgeExtractionOutput(BaseModel):
    """Output from Knowledge Cartographer extraction run."""
    source_id: str
    proposed_claims: list[ProposedClaim]
    proposed_concepts: list[str] = Field(default_factory=list)
    extraction_notes: str = ""
    requires_human_review: bool = True


# ------------------------------------------------------------------
# Curriculum Architect Outputs
# ------------------------------------------------------------------

class ProposedLesson(BaseModel):
    """A lesson proposed by Curriculum Architect. Must reference verified claim IDs."""
    title: str = Field(min_length=3, max_length=200)
    content_summary: str
    claim_ids: list[str] = Field(min_length=1)  # MUST reference existing claims
    estimated_minutes: int = Field(ge=1, le=240)
    requires_human_review: bool = True

    @field_validator("claim_ids")
    @classmethod
    def must_have_claims(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Lesson must reference at least one claim.")
        return v


class ProposedModule(BaseModel):
    """A module proposed by Curriculum Architect."""
    title: str
    description: str
    lessons: list[ProposedLesson]


class CurriculumDraftOutput(BaseModel):
    """Output from Curriculum Architect build run."""
    course_title: str
    course_description: str
    modules: list[ProposedModule]
    claim_ids_used: list[str]
    requires_human_review: bool = True
    notes: str = ""


# ------------------------------------------------------------------
# Integrity Auditor Outputs
# ------------------------------------------------------------------

class ConflictProposal(BaseModel):
    """A detected potential conflict between two claims."""
    claim_a_id: str
    claim_b_id: str
    conflict_description: str
    severity: str = "medium"  # "low" | "medium" | "high"

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, v: str) -> str:
        if v not in ("low", "medium", "high"):
            raise ValueError(f"Invalid severity: {v!r}")
        return v


class IntegrityAuditOutput(BaseModel):
    """Output from Integrity Auditor run."""
    total_claims_checked: int
    proposed_conflicts: list[ConflictProposal]
    outdated_claim_ids: list[str]
    flagged_claim_ids: list[str]
    summary: str
    requires_human_review: bool = True


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

def parse_agent_output(raw: str, schema: type[BaseModel]) -> BaseModel:
    """
    Parse and validate raw LLM JSON output against a Pydantic schema.
    Raises AgentOutputError on parse or validation failure.

    Agents MUST call this before returning results.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgentOutputError(
            f"LLM output is not valid JSON: {exc}\nRaw output: {raw[:500]}"
        ) from exc

    try:
        return schema.model_validate(data)
    except Exception as exc:
        raise AgentOutputError(
            f"LLM output failed schema validation ({schema.__name__}): {exc}\n"
            f"Raw output: {raw[:500]}"
        ) from exc
