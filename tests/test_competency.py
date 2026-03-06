"""Tests for the competency and standards manager."""

import pytest
from core.competency.competency_manager import CompetencyManager, CompetencyError
from core.ingestion.source_registry import SourceRegistry
from core.ingestion.claim_ledger import ClaimLedger
from core.curriculum_engine.curriculum_builder import CurriculumBuilder
from database.schemas.models import SkillLevel, TrustTier, ClaimStatus


async def _setup_verified_claim(session):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Competency Test Source",
        publisher="NATEF Accredited",
        trust_tier=TrustTier.TIER2,
        content=b"Cooling system competency test content.",
    )
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Technicians must identify thermostat failure symptoms.",
        source_id=source.source_id,
    )
    verified = await ledger.verify_claim(claim.claim_id, reviewer="instructor_001")
    return source, verified


async def _setup_published_course(session):
    source, claim = await _setup_verified_claim(session)
    builder = CurriculumBuilder(session)
    course = await builder.create_course(
        title="Competency Test Course",
        academy_node="test_academy",
        source_ids=[source.source_id],
    )
    module = await builder.add_module(course.course_id, title="Module 1", order=1)
    lesson = await builder.add_lesson(
        module.module_id, title="Lesson 1", order=1, claim_ids=[claim.claim_id]
    )
    await builder.publish_course(course.course_id)
    return course, module, lesson, claim


# ---------------------------------------------------------------------------
# Standard tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_standard(session):
    manager = CompetencyManager(session)
    std = await manager.create_standard(
        name="NATEF 2024",
        issuing_body="National Automotive Technicians Education Foundation",
        version="2024",
        description="Automotive technician training standards",
        domain="automotive",
    )
    assert std.standard_id is not None
    assert std.name == "NATEF 2024"
    assert std.issuing_body == "National Automotive Technicians Education Foundation"


@pytest.mark.asyncio
async def test_create_standard_idempotent(session):
    """Creating a standard with the same name returns the existing record."""
    manager = CompetencyManager(session)
    s1 = await manager.create_standard(name="ISO 9001", issuing_body="ISO")
    s2 = await manager.create_standard(name="ISO 9001", issuing_body="ISO")
    assert s1.standard_id == s2.standard_id


@pytest.mark.asyncio
async def test_list_standards(session):
    manager = CompetencyManager(session)
    await manager.create_standard(name="ASE A1", issuing_body="ASE")
    await manager.create_standard(name="ASE A8", issuing_body="ASE")
    standards = await manager.list_standards()
    names = [s.name for s in standards]
    assert "ASE A1" in names
    assert "ASE A8" in names


# ---------------------------------------------------------------------------
# Competency CRUD tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_competency(session):
    manager = CompetencyManager(session)
    comp = await manager.create_competency(
        name="Diagnose Cooling System Faults",
        description="Identify and resolve cooling system failures",
        skill_level=SkillLevel.INTERMEDIATE,
        domain="automotive",
        code="NATEF-A8-01",
        industry_standard_reference="NATEF Task A8-A-1",
    )
    assert comp.competency_id is not None
    assert comp.name == "Diagnose Cooling System Faults"
    assert comp.skill_level == SkillLevel.INTERMEDIATE
    assert comp.code == "NATEF-A8-01"


@pytest.mark.asyncio
async def test_retrieve_competency(session):
    manager = CompetencyManager(session)
    comp = await manager.create_competency(
        name="Inspect Radiator",
        skill_level=SkillLevel.FOUNDATIONAL,
    )
    retrieved = await manager.retrieve_competency(comp.competency_id)
    assert retrieved.competency_id == comp.competency_id
    assert retrieved.name == "Inspect Radiator"


@pytest.mark.asyncio
async def test_retrieve_competency_not_found_raises(session):
    manager = CompetencyManager(session)
    with pytest.raises(CompetencyError, match="Competency not found"):
        await manager.retrieve_competency("nonexistent-id")


@pytest.mark.asyncio
async def test_list_competencies_by_domain(session):
    manager = CompetencyManager(session)
    await manager.create_competency(name="Engine Diagnosis", domain="automotive", skill_level=SkillLevel.ADVANCED)
    await manager.create_competency(name="Civic Research Skills", domain="civic", skill_level=SkillLevel.FOUNDATIONAL)
    results = await manager.list_competencies(domain="automotive")
    domains = {c.domain for c in results}
    assert "automotive" in domains
    assert "civic" not in domains


@pytest.mark.asyncio
async def test_list_competencies_by_skill_level(session):
    manager = CompetencyManager(session)
    await manager.create_competency(name="Basic Tool Use", skill_level=SkillLevel.FOUNDATIONAL)
    await manager.create_competency(name="Advanced Diagnostics", skill_level=SkillLevel.ADVANCED)
    results = await manager.list_competencies(skill_level=SkillLevel.FOUNDATIONAL)
    for c in results:
        assert c.skill_level == SkillLevel.FOUNDATIONAL


# ---------------------------------------------------------------------------
# Mapping tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_map_claim_to_competency(session):
    manager = CompetencyManager(session)
    _, claim = await _setup_verified_claim(session)
    comp = await manager.create_competency(name="Thermostat Knowledge", skill_level=SkillLevel.INTERMEDIATE)
    mapping = await manager.map_claim_to_competency(
        claim.claim_id, comp.competency_id,
        alignment_notes="Claim directly supports this competency."
    )
    assert mapping.mapping_id is not None
    assert mapping.claim_id == claim.claim_id
    assert mapping.competency_id == comp.competency_id


@pytest.mark.asyncio
async def test_map_course_to_competency(session):
    manager = CompetencyManager(session)
    course, _, _, _ = await _setup_published_course(session)
    comp = await manager.create_competency(name="Course-Level Skill", skill_level=SkillLevel.ADVANCED)
    mapping = await manager.map_course_to_competency(course.course_id, comp.competency_id)
    assert mapping.course_id == course.course_id
    assert mapping.competency_id == comp.competency_id


@pytest.mark.asyncio
async def test_map_lesson_to_competency(session):
    manager = CompetencyManager(session)
    _, _, lesson, _ = await _setup_published_course(session)
    comp = await manager.create_competency(name="Lesson-Level Skill", skill_level=SkillLevel.FOUNDATIONAL)
    mapping = await manager.map_lesson_to_competency(lesson.lesson_id, comp.competency_id)
    assert mapping.lesson_id == lesson.lesson_id
    assert mapping.competency_id == comp.competency_id


# ---------------------------------------------------------------------------
# Coverage report tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_competencies_for_course_includes_lesson_competencies(session):
    manager = CompetencyManager(session)
    course, _, lesson, _ = await _setup_published_course(session)

    # Map one competency directly to the course
    c1 = await manager.create_competency(name="Course Competency", skill_level=SkillLevel.ADVANCED)
    await manager.map_course_to_competency(course.course_id, c1.competency_id)

    # Map another via lesson
    c2 = await manager.create_competency(name="Lesson Competency", skill_level=SkillLevel.INTERMEDIATE)
    await manager.map_lesson_to_competency(lesson.lesson_id, c2.competency_id)

    competencies = await manager.get_competencies_for_course(course.course_id)
    comp_ids = [c.competency_id for c in competencies]
    assert c1.competency_id in comp_ids
    assert c2.competency_id in comp_ids


@pytest.mark.asyncio
async def test_competency_coverage_report_structure(session):
    manager = CompetencyManager(session)
    course, _, lesson, claim = await _setup_published_course(session)
    comp = await manager.create_competency(name="Coverage Comp", skill_level=SkillLevel.INTERMEDIATE)
    await manager.map_claim_to_competency(claim.claim_id, comp.competency_id)
    await manager.map_lesson_to_competency(lesson.lesson_id, comp.competency_id)

    report = await manager.get_competency_coverage_report(course.course_id)
    assert report["course_id"] == course.course_id
    assert isinstance(report["competencies"], list)
