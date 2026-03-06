"""
UAE API — Competency & Standards Routes (Part 5)

POST   /standards                         Create a standard
GET    /standards                         List standards
POST   /competencies                      Create a competency
GET    /competencies                      List competencies
GET    /competencies/{id}                 Get a competency
POST   /competencies/{id}/map/claim       Map claim → competency
POST   /competencies/{id}/map/lesson      Map lesson → competency
POST   /competencies/{id}/map/course      Map course → competency
GET    /competencies/course/{id}          Get competencies for a course
GET    /competencies/coverage/{course_id} Coverage report
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.competency.competency_manager import CompetencyManager, CompetencyError
from database.connection import get_async_session
from database.schemas.models import SkillLevel

router = APIRouter(tags=["Competencies & Standards"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateStandardRequest(BaseModel):
    name: str = Field(..., min_length=1)
    issuing_body: str
    version: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    domain: Optional[str] = None


class CreateCompetencyRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    skill_level: str = "foundational"
    domain: Optional[str] = None
    code: Optional[str] = None
    industry_standard_reference: Optional[str] = None
    standard_id: Optional[str] = None
    node_id: Optional[str] = None


class MapRequest(BaseModel):
    alignment_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Standards endpoints
# ---------------------------------------------------------------------------

@router.post("/standards", status_code=status.HTTP_201_CREATED)
async def create_standard(
    body: CreateStandardRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    std = await manager.create_standard(
        name=body.name,
        issuing_body=body.issuing_body,
        version=body.version,
        description=body.description,
        url=body.url,
        domain=body.domain,
    )
    return _std_dict(std)


@router.get("/standards")
async def list_standards(
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    stds = await manager.list_standards(limit=min(limit, 200))
    return [_std_dict(s) for s in stds]


# ---------------------------------------------------------------------------
# Competency endpoints
# ---------------------------------------------------------------------------

@router.post("/competencies", status_code=status.HTTP_201_CREATED)
async def create_competency(
    body: CreateCompetencyRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    try:
        level = SkillLevel(body.skill_level)
        comp = await manager.create_competency(
            name=body.name,
            description=body.description,
            skill_level=level,
            domain=body.domain,
            code=body.code,
            industry_standard_reference=body.industry_standard_reference,
            standard_id=body.standard_id,
            node_id=body.node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _comp_dict(comp)


@router.get("/competencies")
async def list_competencies(
    domain: Optional[str] = None,
    skill_level: Optional[str] = None,
    standard_id: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    level = SkillLevel(skill_level) if skill_level else None
    comps = await manager.list_competencies(
        domain=domain, skill_level=level, standard_id=standard_id, limit=min(limit, 200)
    )
    return [_comp_dict(c) for c in comps]


@router.get("/competencies/{competency_id}")
async def get_competency(
    competency_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    try:
        comp = await manager.retrieve_competency(competency_id)
    except CompetencyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _comp_dict(comp)


# ---------------------------------------------------------------------------
# Mapping endpoints
# ---------------------------------------------------------------------------

@router.post("/competencies/{competency_id}/map/claim/{claim_id}", status_code=status.HTTP_201_CREATED)
async def map_claim(
    competency_id: str,
    claim_id: str,
    body: MapRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    mapping = await manager.map_claim_to_competency(
        claim_id, competency_id, alignment_notes=body.alignment_notes
    )
    return {"mapping_id": mapping.mapping_id, "competency_id": competency_id, "claim_id": claim_id}


@router.post("/competencies/{competency_id}/map/lesson/{lesson_id}", status_code=status.HTTP_201_CREATED)
async def map_lesson(
    competency_id: str,
    lesson_id: str,
    body: MapRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    mapping = await manager.map_lesson_to_competency(
        lesson_id, competency_id, alignment_notes=body.alignment_notes
    )
    return {"mapping_id": mapping.mapping_id, "competency_id": competency_id, "lesson_id": lesson_id}


@router.post("/competencies/{competency_id}/map/course/{course_id}", status_code=status.HTTP_201_CREATED)
async def map_course(
    competency_id: str,
    course_id: str,
    body: MapRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    mapping = await manager.map_course_to_competency(
        course_id, competency_id, alignment_notes=body.alignment_notes
    )
    return {"mapping_id": mapping.mapping_id, "competency_id": competency_id, "course_id": course_id}


@router.get("/competencies/course/{course_id}")
async def get_course_competencies(
    course_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    comps = await manager.get_competencies_for_course(course_id)
    return [_comp_dict(c) for c in comps]


@router.get("/competencies/coverage/{course_id}")
async def get_coverage_report(
    course_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = CompetencyManager(session)
    return await manager.get_competency_coverage_report(course_id)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _std_dict(std) -> dict:
    return {
        "standard_id": std.standard_id,
        "name": std.name,
        "issuing_body": std.issuing_body,
        "version": std.version,
        "domain": std.domain,
        "url": std.url,
        "created_at": std.created_at.isoformat(),
    }


def _comp_dict(comp) -> dict:
    return {
        "competency_id": comp.competency_id,
        "name": comp.name,
        "code": comp.code,
        "description": comp.description,
        "skill_level": comp.skill_level.value if comp.skill_level else None,
        "domain": comp.domain,
        "industry_standard_reference": comp.industry_standard_reference,
        "standard_id": comp.standard_id,
        "is_active": comp.is_active,
        "created_at": comp.created_at.isoformat(),
    }
