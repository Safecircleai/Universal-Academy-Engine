"""Tests for the credential issuer."""

import pytest
from core.credentials.credential_issuer import CredentialIssuer, CredentialError
from core.competency.competency_manager import CompetencyManager
from core.ingestion.source_registry import SourceRegistry
from core.ingestion.claim_ledger import ClaimLedger
from core.curriculum_engine.curriculum_builder import CurriculumBuilder
from core.federation.node_manager import NodeManager
from database.schemas.models import CredentialType, NodeType, SkillLevel, TrustTier


async def _setup_published_course_with_node(session):
    """Bootstrap: node + source + claim + course (published) + competency mapping."""
    node_manager = NodeManager(session)
    node = await node_manager.register_node(
        node_name="Credential Issuer Node",
        node_type=NodeType.VOCATIONAL_ACADEMY,
    )

    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Credential Test Source",
        publisher="NATEF Accredited",
        trust_tier=TrustTier.TIER2,
        content=b"Content for credential issuance testing.",
    )

    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Technicians must verify coolant concentration before winter.",
        source_id=source.source_id,
    )
    claim.origin_node_id = node.node_id
    await session.flush()
    claim = await ledger.verify_claim(claim.claim_id, reviewer="instructor")

    builder = CurriculumBuilder(session)
    course = await builder.create_course(
        title="Credential Test Course",
        academy_node="test_academy",
        source_ids=[source.source_id],
    )
    module = await builder.add_module(course.course_id, title="Module 1", order=1)
    lesson = await builder.add_lesson(
        module.module_id, title="Lesson 1", order=1, claim_ids=[claim.claim_id]
    )
    await builder.publish_course(course.course_id)

    comp_manager = CompetencyManager(session)
    comp = await comp_manager.create_competency(
        name="Coolant Inspection", skill_level=SkillLevel.INTERMEDIATE,
        code="NATEF-A8-02", industry_standard_reference="NATEF A8"
    )
    await comp_manager.map_lesson_to_competency(lesson.lesson_id, comp.competency_id)

    return node, course, comp


# ---------------------------------------------------------------------------
# Issuance tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_issue_credential(session):
    node, course, comp = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)

    cred = await issuer.issue_credential(
        student_id="student-001",
        student_name="Jane Doe",
        student_email="jane@example.com",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
        credential_type=CredentialType.COMPLETION,
    )

    assert cred.credential_id is not None
    assert cred.student_id == "student-001"
    assert cred.course_id == course.course_id
    assert cred.is_revoked is False
    assert cred.credential_hash is not None


@pytest.mark.asyncio
async def test_issue_credential_includes_competencies(session):
    node, course, comp = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)

    cred = await issuer.issue_credential(
        student_id="student-002",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )

    subject = cred.credential_subject
    assert "competencies_mastered" in subject
    competency_codes = [c["code"] for c in subject["competencies_mastered"] if c.get("code")]
    assert "NATEF-A8-02" in competency_codes


@pytest.mark.asyncio
async def test_issue_credential_unpublished_course_raises(session):
    node_manager = NodeManager(session)
    node = await node_manager.register_node(
        node_name="Draft Course Node", node_type=NodeType.CHARTER_SCHOOL
    )
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Draft Source", publisher="Test", trust_tier=TrustTier.TIER3,
        content=b"draft content",
    )
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(statement="Draft claim.", source_id=source.source_id)
    await ledger.verify_claim(claim.claim_id)

    builder = CurriculumBuilder(session)
    course = await builder.create_course(
        title="Draft Course", academy_node="node_a", source_ids=[source.source_id]
    )
    # Do NOT publish the course

    issuer = CredentialIssuer(session)
    with pytest.raises(CredentialError, match="published"):
        await issuer.issue_credential(
            student_id="student-003",
            course_id=course.course_id,
            issuing_node_id=node.node_id,
            issued_by="admin",
        )


@pytest.mark.asyncio
async def test_issue_credential_with_private_key(session):
    """Credential issued with a signing key should have a proof block."""
    from core.attestation.attestation_manager import AttestationManager
    node, course, _ = await _setup_published_course_with_node(session)
    priv, _ = AttestationManager.generate_dev_key_pair()

    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-signed",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
        signing_private_key_pem=priv,
    )

    assert cred.proof is not None
    assert "jws" in cred.proof
    assert cred.verification_signature is not None


# ---------------------------------------------------------------------------
# Revocation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_credential(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-revoke",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )
    assert cred.is_revoked is False

    revoked = await issuer.revoke_credential(
        cred.credential_id,
        reason="Fraudulent completion submitted.",
        revoked_by="admin",
    )
    assert revoked.is_revoked is True
    assert revoked.revoked_at is not None
    assert "Fraudulent" in revoked.revocation_reason


@pytest.mark.asyncio
async def test_revoke_already_revoked_raises(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-double-revoke",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )
    await issuer.revoke_credential(cred.credential_id, reason="First revoke", revoked_by="admin")

    with pytest.raises(CredentialError, match="already revoked"):
        await issuer.revoke_credential(cred.credential_id, reason="Second attempt", revoked_by="admin")


# ---------------------------------------------------------------------------
# Export and verification tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_json(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-json",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )

    doc = await issuer.export_json(cred.credential_id)
    assert "@context" in doc
    assert "VerifiableCredential" in doc["type"]
    assert doc["credentialSubject"]["student_id"] == "student-json"
    assert "issuanceDate" in doc


@pytest.mark.asyncio
async def test_export_json_includes_revocation_status(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-revoked-export",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )
    await issuer.revoke_credential(cred.credential_id, reason="Test revoke", revoked_by="admin")

    doc = await issuer.export_json(cred.credential_id)
    assert "credentialStatus" in doc
    assert doc["credentialStatus"]["revoked"] is True


@pytest.mark.asyncio
async def test_export_portable_token(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-token",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )

    token = await issuer.export_portable_token(cred.credential_id)
    assert isinstance(token, str)
    assert len(token) > 0

    # Token should be Base64-decodeable JSON
    import base64, json
    decoded = json.loads(base64.urlsafe_b64decode(token + "==").decode())
    assert "credentialSubject" in decoded


@pytest.mark.asyncio
async def test_verify_credential_valid(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-verify",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )

    result = await issuer.verify_credential(cred.credential_id)
    assert result["valid"] is True
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_verify_revoked_credential_invalid(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)
    cred = await issuer.issue_credential(
        student_id="student-revoked-verify",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )
    await issuer.revoke_credential(cred.credential_id, reason="Invalid", revoked_by="admin")

    result = await issuer.verify_credential(cred.credential_id)
    assert result["valid"] is False
    assert len(result["errors"]) > 0


@pytest.mark.asyncio
async def test_list_student_credentials(session):
    node, course, _ = await _setup_published_course_with_node(session)
    issuer = CredentialIssuer(session)

    await issuer.issue_credential(
        student_id="student-multi-1",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )
    await issuer.issue_credential(
        student_id="student-multi-1",
        course_id=course.course_id,
        issuing_node_id=node.node_id,
        issued_by="admin",
    )

    creds = await issuer.list_student_credentials("student-multi-1")
    assert len(creds) == 2
    for c in creds:
        assert c.student_id == "student-multi-1"
