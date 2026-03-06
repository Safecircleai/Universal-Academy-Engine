"""
Tests for the AI agent pipeline.
Integration tests that exercise agent-to-module interactions.
"""

import pytest
from agents.source_sentinel import SourceSentinelAgent
from agents.knowledge_cartographer import KnowledgeCartographerAgent
from agents.curriculum_architect import CurriculumArchitectAgent
from agents.integrity_auditor import IntegrityAuditorAgent
from core.ingestion.claim_ledger import ClaimLedger
from database.schemas.models import ClaimStatus


SAMPLE_TEXT = b"""
The cooling system prevents engine overheating by circulating coolant.

The thermostat regulates coolant flow between the engine and radiator.
When coolant temperature exceeds 195 degrees Fahrenheit the thermostat opens.
A stuck thermostat causes engine overheating and should be replaced immediately.

The fan clutch controls cooling airflow through the radiator.
A failed fan clutch causes overheating at idle speed.
Fan clutch replacement requires proper torque specification.

Regular coolant inspection prevents cooling system failures.
Coolant concentration should be checked with a refractometer.
"""


@pytest.mark.asyncio
async def test_source_sentinel_txt(session):
    agent = SourceSentinelAgent(session)
    result = await agent.run({
        "title": "Test Cooling Manual",
        "publisher": "CFRS Technical Institute",
        "content": SAMPLE_TEXT,
        "fmt": "txt",
        "trust_tier": "tier2",
    })
    assert result["source_id"] is not None
    assert result["text_blocks_extracted"] > 0
    assert result["trust_tier"] == "tier2"


@pytest.mark.asyncio
async def test_source_sentinel_tier_classification(session):
    """Publisher containing 'NATEF' should auto-classify as tier2."""
    agent = SourceSentinelAgent(session)
    result = await agent.run({
        "title": "NATEF Manual",
        "publisher": "NATEF Accredited Training",
        "content": b"Sample NATEF content for testing.",
        "fmt": "txt",
    })
    assert result["trust_tier"] == "tier2"


@pytest.mark.asyncio
async def test_knowledge_cartographer_extracts_claims(session):
    # First ingest a source
    sentinel = SourceSentinelAgent(session)
    sentinel_result = await sentinel.run({
        "title": "Cartographer Test Source",
        "publisher": "Test Publisher",
        "content": SAMPLE_TEXT,
        "fmt": "txt",
        "trust_tier": "tier2",
    })
    await session.commit()

    # Then run cartographer
    agent = KnowledgeCartographerAgent(session)
    result = await agent.run({
        "source_id": sentinel_result["source_id"],
        "concept_domain": "cooling_systems",
        "confidence_base": 0.7,
    })
    assert result["claims_created"] > 0


@pytest.mark.asyncio
async def test_curriculum_architect_builds_course(session):
    # Setup: ingest → extract → verify claims
    sentinel = SourceSentinelAgent(session)
    s_result = await sentinel.run({
        "title": "Architect Test Source",
        "publisher": "Curriculum Test",
        "content": SAMPLE_TEXT,
        "fmt": "txt",
        "trust_tier": "tier2",
    })
    await session.commit()

    cartographer = KnowledgeCartographerAgent(session)
    await cartographer.run({
        "source_id": s_result["source_id"],
        "confidence_base": 0.7,
    })
    await session.commit()

    # Verify all draft claims
    ledger = ClaimLedger(session)
    drafts = await ledger.list_claims(
        source_id=s_result["source_id"], status=ClaimStatus.DRAFT, limit=200
    )
    for claim in drafts:
        await ledger.verify_claim(claim.claim_id, reviewer="test_reviewer")
    await session.commit()

    # Now build curriculum
    agent = CurriculumArchitectAgent(session)
    result = await agent.run({
        "course_title": "Cooling System Fundamentals",
        "academy_node": "test_academy",
        "source_ids": [s_result["source_id"]],
    })
    assert result["course_id"] is not None
    assert result["modules_created"] >= 1


@pytest.mark.asyncio
async def test_integrity_auditor_full_mode(session):
    agent = IntegrityAuditorAgent(session)
    result = await agent.run({"mode": "full"})
    assert "conflicts_found" in result
    assert "outdated_found" in result
    assert "flagged_for_review" in result


@pytest.mark.asyncio
async def test_integrity_auditor_conflicts_only(session):
    agent = IntegrityAuditorAgent(session)
    result = await agent.run({"mode": "conflicts_only"})
    assert result["mode"] == "conflicts_only"
    assert "conflicts_found" in result


@pytest.mark.asyncio
async def test_agent_run_is_logged(session):
    """Every agent run must create an AgentRun record."""
    from sqlalchemy import select
    from database.schemas.models import AgentRun

    agent = SourceSentinelAgent(session)
    await agent.run({
        "title": "Log Test Source",
        "publisher": "Log Test",
        "content": b"Logging test content.",
        "fmt": "txt",
    })
    await session.commit()

    stmt = select(AgentRun).where(AgentRun.agent_name == "source_sentinel")
    result = await session.execute(stmt)
    runs = result.scalars().all()
    assert len(runs) >= 1
    assert runs[-1].status.value == "completed"
