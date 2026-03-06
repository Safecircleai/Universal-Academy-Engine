"""Tests for the Verification Engine."""

import pytest
from core.ingestion.claim_ledger import ClaimLedger
from core.ingestion.source_registry import SourceRegistry
from core.knowledge_graph.graph_manager import KnowledgeGraphManager
from core.verification.verification_engine import VerificationEngine
from database.schemas.models import ClaimStatus, RelationshipType, ReviewStatus, TrustTier


async def _make_verified_claim(session, statement, source_id, concept_id=None):
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement=statement,
        source_id=source_id,
        concept_id=concept_id,
        confidence_score=0.75,
    )
    return await ledger.verify_claim(claim.claim_id, reviewer="test")


async def _make_source(session):
    registry = SourceRegistry(session)
    return await registry.register_source(
        title="Test", publisher="Pub", trust_tier=TrustTier.TIER2, content=b"test"
    )


@pytest.mark.asyncio
async def test_detect_conflicts(session):
    source = await _make_source(session)
    graph = KnowledgeGraphManager(session)
    concept, _ = await graph.get_or_create_concept("thermostat")

    # Two conflicting claims on the same concept
    await _make_verified_claim(
        session,
        "The thermostat always increases coolant flow when hot.",
        source.source_id,
        concept.concept_id,
    )
    await _make_verified_claim(
        session,
        "The thermostat never increases coolant flow in bypass mode.",
        source.source_id,
        concept.concept_id,
    )

    engine = VerificationEngine(session)
    flags = await engine.detect_conflicts()
    assert len(flags) >= 1


@pytest.mark.asyncio
async def test_detect_conflicts_no_duplicates(session):
    """Running detect_conflicts twice should not create duplicate flags."""
    source = await _make_source(session)
    graph = KnowledgeGraphManager(session)
    concept, _ = await graph.get_or_create_concept("radiator_valve")

    await _make_verified_claim(
        session, "Valve always opens at high temp.", source.source_id, concept.concept_id
    )
    await _make_verified_claim(
        session, "Valve never opens at high temp.", source.source_id, concept.concept_id
    )

    engine = VerificationEngine(session)
    flags1 = await engine.detect_conflicts()
    flags2 = await engine.detect_conflicts()
    # Second run should add 0 new flags for the same pair
    assert len(flags2) == 0


@pytest.mark.asyncio
async def test_flag_claim_for_review(session):
    source = await _make_source(session)
    claim = await _make_verified_claim(
        session, "Test claim for flagging.", source.source_id
    )
    engine = VerificationEngine(session)
    log = await engine.flag_claim_for_review(
        claim.claim_id, reason="Potential conflict detected."
    )
    assert log.log_id is not None
    assert log.review_status == ReviewStatus.PENDING
    assert log.verification_result == "needs_review"


@pytest.mark.asyncio
async def test_approve_review(session):
    source = await _make_source(session)
    claim = await _make_verified_claim(
        session, "Test claim to approve.", source.source_id
    )
    engine = VerificationEngine(session)
    log = await engine.flag_claim_for_review(claim.claim_id, reason="Testing.")
    approved = await engine.approve_review(log.log_id, reviewer="human_reviewer", notes="Confirmed correct.")
    assert approved.review_status == ReviewStatus.APPROVED
    assert approved.is_ai_review is False


@pytest.mark.asyncio
async def test_reject_review(session):
    source = await _make_source(session)
    claim = await _make_verified_claim(
        session, "Test claim to reject.", source.source_id
    )
    engine = VerificationEngine(session)
    log = await engine.flag_claim_for_review(claim.claim_id, reason="Testing.")
    rejected = await engine.reject_review(log.log_id, reviewer="human_reviewer", notes="Not supported by evidence.")
    assert rejected.review_status == ReviewStatus.REJECTED


@pytest.mark.asyncio
async def test_run_full_audit(session):
    source = await _make_source(session)
    for i in range(3):
        await _make_verified_claim(
            session, f"Audit test claim number {i}.", source.source_id
        )
    engine = VerificationEngine(session)
    report = await engine.run_full_audit()
    assert report.report_id is not None
    assert report.total_claims_checked >= 3
    assert report.summary is not None
