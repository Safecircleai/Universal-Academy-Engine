"""
UAE API — Request Models (Pydantic)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from database.schemas.models import RelationshipType

class RegisterSourceRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    publisher: str = Field(..., min_length=1, max_length=256)
    trust_tier: Optional[str] = Field(None, description="tier1 | tier2 | tier3")
    edition: Optional[str] = None
    publication_date: Optional[str] = Field(None, description="ISO date, e.g. 2023-01-15")
    license: Optional[str] = None
    source_url: Optional[str] = None
    language: str = "en"
    file_path: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("trust_tier")
    @classmethod
    def validate_trust_tier(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        valid = {"tier1", "tier2", "tier3"}
        if v not in valid:
            raise ValueError(
                f"Invalid trust_tier {v!r}. Valid values are: {sorted(valid)}"
            )
        return v


class CreateClaimRequest(BaseModel):
    statement: str = Field(..., min_length=10)
    source_id: str
    concept_id: Optional[str] = None
    citation_location: Optional[str] = None
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: Optional[List[str]] = None


class UpdateClaimStatusRequest(BaseModel):
    new_status: str = Field(..., description="draft | verified | contested | deprecated")
    reason: str = Field(..., min_length=1)
    changed_by: str = Field(default="api_user")


class CreateCourseRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    academy_node: str = Field(..., min_length=1)
    description: Optional[str] = None
    version: str = "1.0"
    learning_objectives: Optional[List[str]] = None
    prerequisite_course_ids: Optional[List[str]] = None


class AddModuleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    description: Optional[str] = None
    order: Optional[int] = None
    estimated_minutes: Optional[int] = None


class AddLessonRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1)
    claim_ids: List[str] = Field(..., min_length=1)
    order: Optional[int] = None
    estimated_minutes: Optional[int] = None


class CreateConceptRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    domain: Optional[str] = None
    aliases: Optional[List[str]] = None


class AddRelationshipRequest(BaseModel):
    parent_name: str = Field(..., min_length=1)
    relationship_type: RelationshipType
    child_name: str = Field(..., min_length=1)
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    source_claim_id: Optional[str] = None


class RunAgentRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class HumanOverrideRequest(BaseModel):
    new_status: str = Field(..., description="verified | contested | deprecated")
    reviewer: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class RunVerificationRequest(BaseModel):
    mode: str = Field(
        default="full",
        description="full | conflicts_only | outdated_only | escalate",
    )
    max_age_days: Optional[int] = None
    escalate_high_confidence: bool = False
