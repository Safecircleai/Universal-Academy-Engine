"""
Tests for UAE v3 Multi-Node Federation Protocol

Covers:
  - Full publish → import → contest → adopt flow
  - Signed message round-trips
  - Governance invariants preserved across nodes
  - Replay protection integration with federation messages
  - Node handshake gating message acceptance
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio

from core.federation.message_signing import build_message, sign_message, verify_message_signature
from core.federation.replay_protection import ReplayProtection, ReplayProtectionError
from core.federation.node_handshake import NodeHandshakeProtocol


def _make_node_handshake(node_id: str) -> NodeHandshakeProtocol:
    """Create a NodeHandshakeProtocol with dev keys."""
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        priv = rsa.generate_private_key(65537, 2048, default_backend())
        priv_pem = priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        pub_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    except ImportError:
        priv_pem, pub_pem = "DUMMY_PRIVATE_KEY", "DUMMY_PUBLIC_KEY"

    return NodeHandshakeProtocol(
        local_node_id=node_id,
        local_private_key_pem=priv_pem,
        local_public_key_pem=pub_pem,
        local_node_url=f"http://{node_id}:8000",
    )


# ------------------------------------------------------------------
# Multi-node protocol state machine tests (DB-backed)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_publish_import_contest_adopt_flow(session):
    """
    Full federation protocol test:
    Node A publishes → Node B imports → Node B contests → Node A adopts.
    All governance invariants preserved.
    """
    from database.schemas.models import (
        AcademyNode, NodeType, Source, TrustTier, Claim, ClaimStatus, ClaimCategory
    )
    from core.federation.claim_federation import ClaimFederationProtocol, FederationError

    # Create two nodes
    node_a = AcademyNode(
        node_name="multi-node-test-a",
        node_type=NodeType.VOCATIONAL_ACADEMY,
        is_federation_member=True,
    )
    node_b = AcademyNode(
        node_name="multi-node-test-b",
        node_type=NodeType.CERTIFICATION_BODY,
        is_federation_member=True,
    )
    session.add_all([node_a, node_b])
    await session.flush()

    # Create source on Node A
    source = Source(
        title="Multi-Node Test Source",
        publisher="Test Publisher",
        trust_tier=TrustTier.TIER1,
        document_hash="sha256:" + "a" * 64,
        origin_node_id=node_a.node_id,
    )
    session.add(source)
    await session.flush()

    # Create verified claim on Node A
    claim = Claim(
        claim_number="MN-001",
        statement="Multi-node test claim for federation protocol validation.",
        source_id=source.source_id,
        status=ClaimStatus.VERIFIED,
        origin_node_id=node_a.node_id,
        confidence_score=0.88,
    )
    session.add(claim)
    await session.flush()

    protocol = ClaimFederationProtocol(session)

    # STEP 1: Node A publishes
    pub_record = await protocol.publish_claim(claim.claim_id, node_a.node_id)
    assert pub_record.action == "publish"
    assert claim.claim_category == ClaimCategory.SHARED

    # STEP 2: Node B imports
    _, imp_record = await protocol.import_claim(claim.claim_id, node_b.node_id)
    assert imp_record.action == "import"
    assert imp_record.target_node_id == node_b.node_id

    # STEP 3: Node B contests
    contest_record = await protocol.contest_claim(
        claim.claim_id, node_b.node_id,
        reason="Missing specificity about temperature coefficients."
    )
    assert contest_record.action == "contest"
    assert claim.claim_category == ClaimCategory.CONTESTED

    # STEP 4: Node A adopts after resolution
    adopt_record = await protocol.adopt_claim(
        claim.claim_id, node_a.node_id,
        resolution_notes="Reviewed contest. Claim is accurate at standard conditions."
    )
    assert adopt_record.action == "adopt"
    assert claim.claim_category == ClaimCategory.IMPORTED

    # Verify full event log
    events = await protocol.list_federation_events(claim_id=claim.claim_id)
    actions = [e.action for e in events]
    assert "publish" in actions
    assert "import" in actions
    assert "contest" in actions
    assert "adopt" in actions
    assert len(events) == 4


@pytest.mark.asyncio
async def test_cannot_publish_draft_claim(session):
    """Governance invariant: only VERIFIED claims may be published."""
    from database.schemas.models import AcademyNode, NodeType, Source, TrustTier, Claim, ClaimStatus
    from core.federation.claim_federation import ClaimFederationProtocol, FederationError

    node = AcademyNode(
        node_name="pub-draft-test",
        node_type=NodeType.VOCATIONAL_ACADEMY,
        is_federation_member=True,
    )
    session.add(node)
    await session.flush()

    source = Source(
        title="Test Source",
        publisher="Publisher",
        trust_tier=TrustTier.TIER2,
        document_hash="sha256:" + "b" * 64,
        origin_node_id=node.node_id,
    )
    session.add(source)
    await session.flush()

    draft_claim = Claim(
        claim_number="DRAFT-001",
        statement="This claim is still a draft.",
        source_id=source.source_id,
        status=ClaimStatus.DRAFT,  # NOT verified
        origin_node_id=node.node_id,
    )
    session.add(draft_claim)
    await session.flush()

    protocol = ClaimFederationProtocol(session)
    with pytest.raises(FederationError, match="Only verified claims"):
        await protocol.publish_claim(draft_claim.claim_id, node.node_id)


@pytest.mark.asyncio
async def test_cannot_import_own_claim(session):
    """Governance invariant: a node cannot import its own claim."""
    from database.schemas.models import AcademyNode, NodeType, Source, TrustTier, Claim, ClaimStatus, ClaimCategory
    from core.federation.claim_federation import ClaimFederationProtocol, FederationError

    node = AcademyNode(
        node_name="self-import-test",
        node_type=NodeType.VOCATIONAL_ACADEMY,
        is_federation_member=True,
    )
    session.add(node)
    await session.flush()

    source = Source(
        title="Self Import Source",
        publisher="Publisher",
        trust_tier=TrustTier.TIER1,
        document_hash="sha256:" + "c" * 64,
        origin_node_id=node.node_id,
    )
    session.add(source)
    await session.flush()

    claim = Claim(
        claim_number="SELF-001",
        statement="Self-import test claim.",
        source_id=source.source_id,
        status=ClaimStatus.VERIFIED,
        origin_node_id=node.node_id,
        claim_category=ClaimCategory.SHARED,
    )
    session.add(claim)
    await session.flush()

    protocol = ClaimFederationProtocol(session)
    with pytest.raises(FederationError, match="already owns"):
        await protocol.import_claim(claim.claim_id, node.node_id)


# ------------------------------------------------------------------
# Signed transport message integration
# ------------------------------------------------------------------

class TestSignedTransportIntegration:
    """End-to-end signed message flow with replay protection."""

    def setup_method(self):
        self.node_a = _make_node_handshake("node-a-transport")
        self.node_b = _make_node_handshake("node-b-transport")
        # Mutual handshake
        self.node_b.receive_hello(self.node_a.build_hello())
        self.node_a.receive_hello(self.node_b.build_hello())
        self.replay = ReplayProtection(window_secs=300)

    def _sign_as_node_a(self, message_type: str, body: dict) -> dict:
        msg = build_message(message_type, "node-a-transport", body)
        priv_pem = self.node_a._private_key_pem
        return sign_message(msg, priv_pem)

    def test_node_b_accepts_signed_message_from_node_a(self):
        signed = self._sign_as_node_a("PUBLISH_CLAIM", {"claim_id": "c1"})
        pub_key = self.node_b.get_peer_public_key("node-a-transport")
        assert pub_key is not None
        self.replay.check_and_record(signed)  # replay check passes
        assert verify_message_signature(signed, pub_key)

    def test_replay_rejected_on_second_receive(self):
        signed = self._sign_as_node_a("PUBLISH_CLAIM", {"claim_id": "c2"})
        self.replay.check_and_record(signed)
        with pytest.raises(ReplayProtectionError):
            self.replay.check_and_record(signed)

    def test_untrusted_node_message_rejected(self):
        # Node C has not completed handshake with B
        node_c = _make_node_handshake("node-c-unknown")
        msg = build_message("PUBLISH_CLAIM", "node-c-unknown", {"claim_id": "cx"})
        signed = sign_message(msg, node_c._private_key_pem)
        # Node B has no public key for node-c
        assert self.node_b.get_peer_public_key("node-c-unknown") is None
