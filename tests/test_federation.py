"""Tests for the federation layer — node management and claim federation protocol."""

import pytest
from core.federation.node_manager import NodeManager, NodeManagerError
from core.federation.claim_federation import ClaimFederationProtocol, FederationError
from core.ingestion.source_registry import SourceRegistry
from core.ingestion.claim_ledger import ClaimLedger
from database.schemas.models import (
    ClaimCategory, ClaimStatus, NodeType, TrustTier
)


async def _make_node(session, name="Test Academy", node_type=NodeType.VOCATIONAL_ACADEMY):
    manager = NodeManager(session)
    return await manager.register_node(node_name=name, node_type=node_type)


async def _make_verified_claim(session, source_id, origin_node_id=None):
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="The cooling system prevents engine overheating.",
        source_id=source_id,
    )
    if origin_node_id:
        claim.origin_node_id = origin_node_id
        await session.flush()
    return await ledger.verify_claim(claim.claim_id)


async def _make_source(session, node_id=None):
    registry = SourceRegistry(session)
    return await registry.register_source(
        title="Fed Test Source", publisher="Publisher",
        trust_tier=TrustTier.TIER2, content=b"federation test content"
    )


# ---------------------------------------------------------------------------
# Node Manager tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_node(session):
    manager = NodeManager(session)
    node = await manager.register_node(
        node_name="CFRS Academy",
        node_type=NodeType.VOCATIONAL_ACADEMY,
        description="Fleet maintenance vocational training",
    )
    assert node.node_id is not None
    assert node.node_name == "CFRS Academy"
    assert node.is_active is True
    assert node.is_federation_member is False


@pytest.mark.asyncio
async def test_register_node_duplicate_name_raises(session):
    manager = NodeManager(session)
    await manager.register_node(node_name="Unique Academy", node_type=NodeType.CHARTER_SCHOOL)
    with pytest.raises(NodeManagerError, match="already registered"):
        await manager.register_node(node_name="Unique Academy", node_type=NodeType.CHARTER_SCHOOL)


@pytest.mark.asyncio
async def test_register_node_creates_default_policy(session):
    manager = NodeManager(session)
    node = await manager.register_node(node_name="Policy Node", node_type=NodeType.UNIVERSITY)
    policy = await manager.get_governance_policy(node.node_id)
    assert policy is not None
    assert policy.required_reviewers == 1
    assert policy.verification_threshold == 0.75


@pytest.mark.asyncio
async def test_admit_to_federation(session):
    node = await _make_node(session, "Federation Candidate")
    manager = NodeManager(session)
    assert node.is_federation_member is False
    admitted = await manager.admit_to_federation(node.node_id)
    assert admitted.is_federation_member is True
    assert admitted.joined_federation_at is not None


@pytest.mark.asyncio
async def test_list_federation_members_only(session):
    manager = NodeManager(session)
    n1 = await manager.register_node(node_name="Member Node", node_type=NodeType.VOCATIONAL_ACADEMY)
    n2 = await manager.register_node(node_name="Non-Member Node", node_type=NodeType.CHARTER_SCHOOL)
    await manager.admit_to_federation(n1.node_id)
    members = await manager.list_nodes(federation_members_only=True)
    member_ids = [n.node_id for n in members]
    assert n1.node_id in member_ids
    assert n2.node_id not in member_ids


@pytest.mark.asyncio
async def test_update_governance_policy(session):
    node = await _make_node(session, "Policy Update Node")
    manager = NodeManager(session)
    policy = await manager.update_governance_policy(
        node.node_id,
        minimum_source_tier=TrustTier.TIER1,
        required_reviewers=3,
        verification_threshold=0.9,
        allow_claim_publication=True,
    )
    assert policy.minimum_source_tier == TrustTier.TIER1
    assert policy.required_reviewers == 3
    assert policy.verification_threshold == 0.9
    assert policy.allow_claim_publication is True


@pytest.mark.asyncio
async def test_policy_compliance_check(session):
    node = await _make_node(session, "Compliance Node")
    manager = NodeManager(session)
    await manager.update_governance_policy(
        node.node_id,
        minimum_source_tier=TrustTier.TIER1,
    )
    # Tier3 should fail
    result = await manager.check_policy_compliance(
        node.node_id, source_tier=TrustTier.TIER3
    )
    assert result["compliant"] is False
    assert len(result["violations"]) > 0

    # Tier1 should pass
    result2 = await manager.check_policy_compliance(
        node.node_id, source_tier=TrustTier.TIER1
    )
    assert result2["compliant"] is True


# ---------------------------------------------------------------------------
# Claim Federation Protocol tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_claim_sets_shared_category(session):
    node = await _make_node(session, "Publishing Node")
    await NodeManager(session).update_governance_policy(
        node.node_id, allow_claim_publication=True
    )
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id, origin_node_id=node.node_id)

    protocol = ClaimFederationProtocol(session)
    record = await protocol.publish_claim(claim.claim_id, node.node_id)

    assert record.action == "publish"
    assert claim.claim_category == ClaimCategory.SHARED
    assert claim.publishing_node_id == node.node_id


@pytest.mark.asyncio
async def test_publish_draft_claim_raises(session):
    node = await _make_node(session, "Draft Pub Node")
    await NodeManager(session).update_governance_policy(
        node.node_id, allow_claim_publication=True
    )
    source = await _make_source(session)
    ledger = ClaimLedger(session)
    draft_claim = await ledger.create_claim(
        statement="Draft claim cannot be published.", source_id=source.source_id
    )
    draft_claim.origin_node_id = node.node_id
    await session.flush()

    protocol = ClaimFederationProtocol(session)
    with pytest.raises(FederationError, match="Only verified claims"):
        await protocol.publish_claim(draft_claim.claim_id, node.node_id)


@pytest.mark.asyncio
async def test_import_claim(session):
    pub_node = await _make_node(session, "Publisher Node A")
    imp_node = await _make_node(session, "Importer Node A")
    await NodeManager(session).update_governance_policy(
        pub_node.node_id, allow_claim_publication=True
    )
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id, origin_node_id=pub_node.node_id)

    protocol = ClaimFederationProtocol(session)
    await protocol.publish_claim(claim.claim_id, pub_node.node_id)
    _, record = await protocol.import_claim(claim.claim_id, imp_node.node_id)

    assert record.action == "import"
    assert record.target_node_id == imp_node.node_id


@pytest.mark.asyncio
async def test_contest_and_adopt_claim(session):
    pub_node = await _make_node(session, "Pub Node Contest")
    contest_node = await _make_node(session, "Contest Node")
    await NodeManager(session).update_governance_policy(
        pub_node.node_id, allow_claim_publication=True
    )
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id, origin_node_id=pub_node.node_id)

    protocol = ClaimFederationProtocol(session)
    await protocol.publish_claim(claim.claim_id, pub_node.node_id)

    # Contest
    await protocol.contest_claim(
        claim.claim_id, contest_node.node_id,
        reason="Evidence contradicts this claim under FMCSA 2024 update."
    )
    assert claim.claim_category == ClaimCategory.CONTESTED

    # Adopt (resolve)
    adopt_record = await protocol.adopt_claim(
        claim.claim_id, contest_node.node_id,
        resolution_notes="Reviewed and confirmed valid under new interpretation."
    )
    assert adopt_record.action == "adopt"
    assert claim.claim_category == ClaimCategory.IMPORTED


@pytest.mark.asyncio
async def test_federation_events_logged(session):
    pub_node = await _make_node(session, "Event Log Node")
    await NodeManager(session).update_governance_policy(
        pub_node.node_id, allow_claim_publication=True
    )
    source = await _make_source(session)
    claim = await _make_verified_claim(session, source.source_id, origin_node_id=pub_node.node_id)

    protocol = ClaimFederationProtocol(session)
    await protocol.publish_claim(claim.claim_id, pub_node.node_id)

    events = await protocol.list_federation_events(claim_id=claim.claim_id)
    assert len(events) == 1
    assert events[0].action == "publish"
