"""
UAE API — Response Models (Pydantic)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel


class SourceResponse(BaseModel):
    source_id: str
    title: str
    publisher: str
    trust_tier: str
    document_hash: str
    edition: Optional[str]
    publication_date: Optional[datetime]
    license: Optional[str]
    source_url: Optional[str]
    language: str
    is_active: bool
    ingest_timestamp: datetime

    model_config = {"from_attributes": True}


class ClaimResponse(BaseModel):
    claim_id: str
    claim_number: Optional[str]
    statement: str
    source_id: str
    concept_id: Optional[str]
    citation_location: Optional[str]
    confidence_score: float
    status: str
    tags: Optional[List[str]]
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ConceptResponse(BaseModel):
    concept_id: str
    name: str
    description: Optional[str]
    domain: Optional[str]
    aliases: Optional[List[str]]
    created_at: datetime

    model_config = {"from_attributes": True}


class LessonResponse(BaseModel):
    lesson_id: str
    module_id: str
    title: str
    content: str
    order: int
    has_quiz: bool
    estimated_minutes: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class ModuleResponse(BaseModel):
    module_id: str
    course_id: str
    title: str
    description: Optional[str]
    order: int
    estimated_minutes: Optional[int]
    created_at: datetime
    lessons: List[LessonResponse] = []

    model_config = {"from_attributes": True}


class CourseResponse(BaseModel):
    course_id: str
    title: str
    academy_node: str
    description: Optional[str]
    version: str
    is_published: bool
    learning_objectives: Optional[List[str]]
    created_at: datetime
    modules: List[ModuleResponse] = []

    model_config = {"from_attributes": True}


class AgentRunResponse(BaseModel):
    run_id: str
    agent_name: str
    status: str
    output_summary: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class IntegrityReportResponse(BaseModel):
    report_id: str
    run_by: str
    total_claims_checked: int
    conflicts_found: int
    outdated_claims: int
    flagged_for_review: int
    summary: Optional[str]
    details: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class ValidationResponse(BaseModel):
    source_id: str
    valid: bool
    issues: List[str]


class SubgraphResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


class AuditTrailResponse(BaseModel):
    claim_id: str
    revisions: List[Dict[str, Any]]
    verification_logs: List[Dict[str, Any]]


class PipelineRunResponse(BaseModel):
    source_id: str
    cartographer_result: Dict[str, Any]
    message: str
