"""Tests for the cryptographic attestation manager."""

import pytest
from core.attestation.attestation_manager import AttestationManager, AttestationError
from core.ingestion.claim_ledger import ClaimLedger
from core.ingestion.source_registry import SourceRegistry
from database.schemas.models import TrustTier


async def _make_source(session):
    registry = SourceRegistry(session)
    return await registry.register_source(
        title="Attestation Test Source",
        publisher="Test Publisher",
        trust_tier=TrustTier.TIER1,
        content=b"Attestation test content about engine cooling.",
    )


async def _make_verified_claim(session, source_id):
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="The thermostat regulates coolant flow between engine and radiator.",
        source_id=source_id,
    )
    return await ledger.verify_claim(claim.claim_id, reviewer="test_reviewer")


# ---------------------------------------------------------------------------
# Key management tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_dev_key_pair():
    priv, pub = AttestationManager.generate_dev_key_pair()
    assert priv is not None
    assert pub is not None
    assert isinstance(priv, str)
    assert isinstance(pub, str)


@pytest.mark.asyncio
async def test_register_reviewer_key(session):
    manager = AttestationManager(session)
    _, pub = AttestationManager.generate_dev_key_pair()

    key = await manager.register_reviewer_key(
        node_id="test-node-001",
        reviewer_id="reviewer_alice",
        reviewer_name="Alice Smith",
        reviewer_role="lead_instructor",
        reviewer_credentials=["ASE-P2", "NATEF"],
        public_key_pem=pub,
        signature_algorithm="RSA-SHA256",
    )

    assert key.key_id is not None
    assert key.reviewer_id == "reviewer_alice"
    assert key.reviewer_name == "Alice Smith"
    assert key.is_active is True
    assert key.key_fingerprint is not None


@pytest.mark.asyncio
async def test_register_reviewer_key_idempotent(session):
    """Registering the same public key twice returns the existing record."""
    manager = AttestationManager(session)
    _, pub = AttestationManager.generate_dev_key_pair()

    k1 = await manager.register_reviewer_key(
        node_id="node-x", reviewer_id="rev1", public_key_pem=pub
    )
    k2 = await manager.register_reviewer_key(
        node_id="node-x", reviewer_id="rev1", public_key_pem=pub
    )
    assert k1.key_id == k2.key_id


@pytest.mark.asyncio
async def test_get_reviewer_key(session):
    manager = AttestationManager(session)
    _, pub = AttestationManager.generate_dev_key_pair()
    await manager.register_reviewer_key(
        node_id="node-lookup", reviewer_id="reviewer_bob", public_key_pem=pub
    )
    key = await manager.get_reviewer_key("reviewer_bob", "node-lookup")
    assert key is not None
    assert key.reviewer_id == "reviewer_bob"


# ---------------------------------------------------------------------------
# Attestation creation and verification tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_verify_attestation(session):
    manager = AttestationManager(session)
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id)

    priv, pub = AttestationManager.generate_dev_key_pair()
    key = await manager.register_reviewer_key(
        node_id="attest-node", reviewer_id="reviewer_carol", public_key_pem=pub
    )

    # Build the canonical payload and sign it
    from core.attestation.attestation_manager import _hash_statement
    claim_hash = _hash_statement(claim.statement)
    payload_dict = AttestationManager.build_signing_payload(
        claim.claim_id, claim_hash, "reviewer_carol"
    )
    import json
    payload_str = json.dumps(payload_dict, sort_keys=True)
    signature = AttestationManager.sign_payload(priv, payload_str)

    attestation = await manager.create_attestation(
        claim_id=claim.claim_id,
        reviewer_key_id=key.key_id,
        reviewer_id="reviewer_carol",
        reviewer_role="senior_reviewer",
        reviewer_signature=signature,
        verification_reason="Manually verified against FMCSA 2023 spec.",
    )

    assert attestation.attestation_id is not None
    assert attestation.claim_id == claim.claim_id
    assert attestation.signature_verified is True


@pytest.mark.asyncio
async def test_attestation_invalid_signature_stored_but_flagged(session):
    """Invalid signatures are stored but marked as not verified."""
    manager = AttestationManager(session)
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id)

    _, pub = AttestationManager.generate_dev_key_pair()
    key = await manager.register_reviewer_key(
        node_id="flag-node", reviewer_id="reviewer_dan", public_key_pem=pub
    )

    attestation = await manager.create_attestation(
        claim_id=claim.claim_id,
        reviewer_key_id=key.key_id,
        reviewer_id="reviewer_dan",
        reviewer_signature="BADSIGNATURE==",
    )

    assert attestation.attestation_id is not None
    assert attestation.signature_verified is False


@pytest.mark.asyncio
async def test_create_attestation_missing_key_raises(session):
    manager = AttestationManager(session)
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id)

    with pytest.raises(AttestationError, match="ReviewerKey not found"):
        await manager.create_attestation(
            claim_id=claim.claim_id,
            reviewer_key_id="nonexistent-key-id",
            reviewer_id="reviewer_x",
            reviewer_signature="sig",
        )


@pytest.mark.asyncio
async def test_verify_attestation(session):
    manager = AttestationManager(session)
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id)

    priv, pub = AttestationManager.generate_dev_key_pair()
    key = await manager.register_reviewer_key(
        node_id="verify-node", reviewer_id="reviewer_eve", public_key_pem=pub
    )

    from core.attestation.attestation_manager import _hash_statement
    import json
    claim_hash = _hash_statement(claim.statement)
    payload_str = json.dumps(
        AttestationManager.build_signing_payload(claim.claim_id, claim_hash, "reviewer_eve"),
        sort_keys=True,
    )
    signature = AttestationManager.sign_payload(priv, payload_str)

    att = await manager.create_attestation(
        claim_id=claim.claim_id,
        reviewer_key_id=key.key_id,
        reviewer_id="reviewer_eve",
        reviewer_signature=signature,
    )

    result = await manager.verify_attestation(att.attestation_id)
    assert result["valid"] is True
    assert result["claim_id"] == claim.claim_id
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_get_claim_attestations(session):
    manager = AttestationManager(session)
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id)

    priv, pub = AttestationManager.generate_dev_key_pair()
    key = await manager.register_reviewer_key(
        node_id="multi-att-node", reviewer_id="reviewer_frank", public_key_pem=pub
    )

    from core.attestation.attestation_manager import _hash_statement
    import json
    claim_hash = _hash_statement(claim.statement)
    payload_str = json.dumps(
        AttestationManager.build_signing_payload(claim.claim_id, claim_hash, "reviewer_frank"),
        sort_keys=True,
    )
    signature = AttestationManager.sign_payload(priv, payload_str)

    await manager.create_attestation(
        claim_id=claim.claim_id,
        reviewer_key_id=key.key_id,
        reviewer_id="reviewer_frank",
        reviewer_signature=signature,
    )

    attestations = await manager.get_claim_attestations(claim.claim_id)
    assert len(attestations) == 1
    assert attestations[0].reviewer_id == "reviewer_frank"


@pytest.mark.asyncio
async def test_build_signing_payload_structure():
    payload = AttestationManager.build_signing_payload(
        "claim-abc", "hash-xyz", "reviewer-001"
    )
    assert payload["claim_id"] == "claim-abc"
    assert payload["claim_hash"] == "hash-xyz"
    assert payload["reviewer_id"] == "reviewer-001"
    assert payload["schema_version"] == "uae-attestation-v1"
