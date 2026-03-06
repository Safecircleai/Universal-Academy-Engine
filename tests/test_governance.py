"""Tests for the Governance Manager."""

import pytest
from core.governance.governance_manager import GovernanceManager
from core.ingestion.claim_ledger import ClaimLedger
from core.ingestion.source_registry import SourceRegistry
from database.schemas.models import AgentRunStatus, ClaimStatus, TrustTier


async def _make_verified_claim(session, statement="Test governance claim."):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Gov Test Source", publisher="Pub",
        trust_tier=TrustTier.TIER1, content=statement.encode()
    )
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement=statement, source_id=source.source_id, confidence_score=0.8
    )
    return await ledger.verify_claim(claim.claim_id)


@pytest.mark.asyncio
async def test_agent_run_lifecycle(session):
    gov = GovernanceManager(session)
    run = await gov.start_agent_run("test_agent", {"key": "value"})
    assert run.run_id is not None
    assert run.status == AgentRunStatus.RUNNING

    completed = await gov.complete_agent_run(
        run.run_id, output_summary={"result": "ok"}
    )
    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_agent_run_failure(session):
    gov = GovernanceManager(session)
    run = await gov.start_agent_run("failing_agent", {})
    failed = await gov.complete_agent_run(
        run.run_id, error_message="Connection timeout."
    )
    assert failed.status == AgentRunStatus.FAILED
    assert failed.error_message == "Connection timeout."


@pytest.mark.asyncio
async def test_human_override_claim(session):
    claim = await _make_verified_claim(session, "Claim to be overridden.")
    assert claim.status == ClaimStatus.VERIFIED

    gov = GovernanceManager(session)
    overridden = await gov.human_override_claim(
        claim.claim_id,
        ClaimStatus.DEPRECATED,
        reviewer="senior_reviewer",
        reason="Superseded by 2024 regulation.",
    )
    assert overridden.status == ClaimStatus.DEPRECATED


@pytest.mark.asyncio
async def test_get_claim_audit_trail(session):
    claim = await _make_verified_claim(session, "Audit trail test claim.")
    gov = GovernanceManager(session)
    trail = await gov.get_claim_audit_trail(claim.claim_id)

    assert trail["claim_id"] == claim.claim_id
    assert isinstance(trail["revisions"], list)
    assert isinstance(trail["verification_logs"], list)
    # Should have at least one revision from verification
    assert len(trail["revisions"]) >= 1


@pytest.mark.asyncio
async def test_escalate_high_confidence_claims(session):
    """Claims with confidence ≥ 0.95 should be escalated for mandatory human review."""
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="High Conf Source", publisher="Pub",
        trust_tier=TrustTier.TIER1, content=b"high confidence"
    )
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Very high confidence technical claim.",
        source_id=source.source_id,
        confidence_score=0.97,  # Above threshold
    )
    await ledger.verify_claim(claim.claim_id)

    gov = GovernanceManager(session)
    escalated = await gov.escalate_high_confidence_claims()
    escalated_ids = [c.claim_id for c in escalated]
    assert claim.claim_id in escalated_ids


@pytest.mark.asyncio
async def test_escalate_not_duplicated(session):
    """Running escalation twice should not create duplicate review logs."""
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Dup Esc Source", publisher="Pub",
        trust_tier=TrustTier.TIER1, content=b"dup escalate"
    )
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Claim for duplicate escalation test.",
        source_id=source.source_id,
        confidence_score=0.98,
    )
    await ledger.verify_claim(claim.claim_id)

    gov = GovernanceManager(session)
    first = await gov.escalate_high_confidence_claims()
    second = await gov.escalate_high_confidence_claims()

    # Second run should not re-escalate claims that already have escalation
    first_ids = {c.claim_id for c in first}
    second_ids = {c.claim_id for c in second}
    assert claim.claim_id not in second_ids
