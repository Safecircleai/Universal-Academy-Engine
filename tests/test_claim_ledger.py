"""Tests for the Claim Ledger module."""

import pytest
from core.ingestion.claim_ledger import ClaimLedger, ClaimLedgerError
from core.ingestion.source_registry import SourceRegistry
from database.schemas.models import ClaimStatus, TrustTier


async def _make_source(session):
    registry = SourceRegistry(session)
    return await registry.register_source(
        title="Test Source",
        publisher="Test Publisher",
        trust_tier=TrustTier.TIER2,
        content=b"test content for claims",
    )


@pytest.mark.asyncio
async def test_create_claim(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="The thermostat regulates coolant flow.",
        source_id=source.source_id,
        confidence_score=0.85,
        tags=["thermostat", "coolant"],
    )
    assert claim.claim_id is not None
    assert claim.claim_number.startswith("CLM")
    assert claim.status == ClaimStatus.DRAFT
    assert claim.confidence_score == 0.85


@pytest.mark.asyncio
async def test_create_claim_invalid_source(session):
    ledger = ClaimLedger(session)
    with pytest.raises(ClaimLedgerError, match="Source not found"):
        await ledger.create_claim(
            statement="Some statement.",
            source_id="non-existent-source-id",
        )


@pytest.mark.asyncio
async def test_create_claim_empty_statement(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    with pytest.raises(ClaimLedgerError, match="empty"):
        await ledger.create_claim(
            statement="   ",
            source_id=source.source_id,
        )


@pytest.mark.asyncio
async def test_verify_claim(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Coolant temperature should be between 180°F and 210°F.",
        source_id=source.source_id,
    )
    verified = await ledger.verify_claim(claim.claim_id, reviewer="domain_expert")
    assert verified.status == ClaimStatus.VERIFIED
    assert verified.version == 2


@pytest.mark.asyncio
async def test_cannot_verify_already_verified(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="The fan clutch controls airflow.",
        source_id=source.source_id,
    )
    await ledger.verify_claim(claim.claim_id)
    with pytest.raises(ClaimLedgerError, match="only 'draft' claims can be verified"):
        await ledger.verify_claim(claim.claim_id)


@pytest.mark.asyncio
async def test_update_claim_status_valid_transition(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Fan clutch failure causes overheating.",
        source_id=source.source_id,
    )
    await ledger.verify_claim(claim.claim_id)
    contested = await ledger.update_claim_status(
        claim.claim_id,
        ClaimStatus.CONTESTED,
        reason="Contradicted by new OEM bulletin.",
        changed_by="reviewer",
    )
    assert contested.status == ClaimStatus.CONTESTED


@pytest.mark.asyncio
async def test_invalid_transition_deprecated_to_verified(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Old claim statement.",
        source_id=source.source_id,
    )
    await ledger.update_claim_status(
        claim.claim_id, ClaimStatus.DEPRECATED, reason="Outdated."
    )
    with pytest.raises(ClaimLedgerError, match="Invalid status transition"):
        await ledger.update_claim_status(
            claim.claim_id, ClaimStatus.VERIFIED, reason="Trying to re-verify."
        )


@pytest.mark.asyncio
async def test_claim_revision_history(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Thermostat bypass prevents hot spots.",
        source_id=source.source_id,
    )
    await ledger.verify_claim(claim.claim_id, reviewer="reviewer_1")
    await ledger.update_claim_status(
        claim.claim_id, ClaimStatus.DEPRECATED, reason="Updated by v2 manual."
    )
    history = await ledger.get_claim_history(claim.claim_id)
    assert len(history) == 2
    assert history[0].previous_version == "draft"
    assert history[1].previous_version == "verified"


@pytest.mark.asyncio
async def test_list_claims_by_status(session):
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    claim1 = await ledger.create_claim(
        statement="Draft claim number one.", source_id=source.source_id
    )
    claim2 = await ledger.create_claim(
        statement="Draft claim number two.", source_id=source.source_id
    )
    await ledger.verify_claim(claim1.claim_id)

    verified = await ledger.list_claims(status=ClaimStatus.VERIFIED)
    draft = await ledger.list_claims(status=ClaimStatus.DRAFT)

    verified_ids = [c.claim_id for c in verified]
    draft_ids = [c.claim_id for c in draft]

    assert claim1.claim_id in verified_ids
    assert claim2.claim_id in draft_ids
