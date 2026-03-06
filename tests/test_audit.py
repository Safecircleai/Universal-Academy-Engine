"""Tests for the audit and transparency manager."""

import pytest
from core.audit.audit_manager import AuditManager
from core.credentials.credential_issuer import CredentialIssuer
from core.federation.node_manager import NodeManager
from core.ingestion.claim_ledger import ClaimLedger
from core.ingestion.source_registry import SourceRegistry
from core.curriculum_engine.curriculum_builder import CurriculumBuilder
from database.schemas.models import NodeType, TrustTier


async def _make_node(session, name="Audit Node"):
    manager = NodeManager(session)
    return await manager.register_node(node_name=name, node_type=NodeType.VOCATIONAL_ACADEMY)


async def _make_source_and_claim(session):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Audit Test Source",
        publisher="Test Publisher",
        trust_tier=TrustTier.TIER1,
        content=b"Audit test content about cooling systems.",
    )
    ledger = ClaimLedger(session)
    claim = await ledger.create_claim(
        statement="Engine coolant must be inspected every 30,000 miles.",
        source_id=source.source_id,
    )
    verified = await ledger.verify_claim(claim.claim_id, reviewer="auditor_001")
    return source, verified


async def _make_published_course(session, source, claim):
    builder = CurriculumBuilder(session)
    course = await builder.create_course(
        title="Audit Test Course",
        academy_node="audit_academy",
        source_ids=[source.source_id],
    )
    module = await builder.add_module(course.course_id, title="Module 1", order=1)
    await builder.add_lesson(
        module.module_id, title="Lesson 1", order=1, claim_ids=[claim.claim_id]
    )
    await builder.publish_course(course.course_id)
    return course


# ---------------------------------------------------------------------------
# Claim audit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_claim_returns_report(session):
    _, claim = await _make_source_and_claim(session)
    manager = AuditManager(session)
    report = await manager.audit_claim(claim.claim_id)

    assert report.audit_id is not None
    assert report.report_type == "claim"
    assert report.subject_id == claim.claim_id
    assert report.findings is not None


@pytest.mark.asyncio
async def test_audit_claim_findings_structure(session):
    source, claim = await _make_source_and_claim(session)
    manager = AuditManager(session)
    report = await manager.audit_claim(claim.claim_id)

    findings = report.findings
    assert "claim" in findings
    assert "source" in findings
    assert "revision_history" in findings
    assert "verification_logs" in findings
    assert "attestations" in findings
    assert "federation_events" in findings
    assert "cited_in_lessons" in findings

    assert findings["claim"]["claim_id"] == claim.claim_id
    assert findings["source"]["source_id"] == source.source_id


@pytest.mark.asyncio
async def test_audit_claim_reflects_verification_logs(session):
    _, claim = await _make_source_and_claim(session)
    manager = AuditManager(session)
    report = await manager.audit_claim(claim.claim_id)

    logs = report.findings["verification_logs"]
    assert len(logs) >= 1
    assert logs[0]["reviewer"] == "auditor_001"


@pytest.mark.asyncio
async def test_audit_claim_not_found_raises(session):
    manager = AuditManager(session)
    with pytest.raises(ValueError, match="Claim not found"):
        await manager.audit_claim("nonexistent-claim-id")


@pytest.mark.asyncio
async def test_audit_claim_shows_lesson_citations(session):
    source, claim = await _make_source_and_claim(session)
    await _make_published_course(session, source, claim)

    manager = AuditManager(session)
    report = await manager.audit_claim(claim.claim_id)

    cited = report.findings["cited_in_lessons"]
    assert len(cited) >= 1


# ---------------------------------------------------------------------------
# Course audit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_course_returns_report(session):
    source, claim = await _make_source_and_claim(session)
    course = await _make_published_course(session, source, claim)
    manager = AuditManager(session)

    report = await manager.audit_course(course.course_id)

    assert report.audit_id is not None
    assert report.report_type == "course"
    assert report.subject_id == course.course_id


@pytest.mark.asyncio
async def test_audit_course_findings_structure(session):
    source, claim = await _make_source_and_claim(session)
    course = await _make_published_course(session, source, claim)
    manager = AuditManager(session)
    report = await manager.audit_course(course.course_id)

    findings = report.findings
    assert "course" in findings
    assert "modules" in findings
    assert "summary_stats" in findings

    assert findings["course"]["course_id"] == course.course_id
    assert findings["summary_stats"]["total_modules"] == 1
    assert findings["summary_stats"]["total_lessons"] == 1
    assert findings["summary_stats"]["unique_claims_referenced"] == 1


@pytest.mark.asyncio
async def test_audit_course_not_found_raises(session):
    manager = AuditManager(session)
    with pytest.raises(ValueError, match="Course not found"):
        await manager.audit_course("nonexistent-course-id")


# ---------------------------------------------------------------------------
# Node audit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_node_returns_report(session):
    node = await _make_node(session, "Node Audit Test")
    manager = AuditManager(session)
    report = await manager.audit_node(node.node_id)

    assert report.audit_id is not None
    assert report.report_type == "node"
    assert report.subject_id == node.node_id


@pytest.mark.asyncio
async def test_audit_node_findings_structure(session):
    node = await _make_node(session, "Structure Test Node")
    manager = AuditManager(session)
    report = await manager.audit_node(node.node_id)

    findings = report.findings
    assert "node" in findings
    assert "governance_policy" in findings
    assert "knowledge_stats" in findings

    assert findings["node"]["node_id"] == node.node_id
    assert findings["node"]["node_name"] == "Structure Test Node"
    assert "required_reviewers" in findings["governance_policy"]
    assert "total_claims_originated" in findings["knowledge_stats"]


@pytest.mark.asyncio
async def test_audit_node_not_found_raises(session):
    manager = AuditManager(session)
    with pytest.raises(ValueError, match="Node not found"):
        await manager.audit_node("nonexistent-node-id")


@pytest.mark.asyncio
async def test_audit_node_knowledge_stats(session):
    node = await _make_node(session, "Stats Node")
    source, claim = await _make_source_and_claim(session)
    # Assign origin node
    claim.origin_node_id = node.node_id
    await session.flush()

    manager = AuditManager(session)
    report = await manager.audit_node(node.node_id)
    stats = report.findings["knowledge_stats"]

    assert stats["total_claims_originated"] >= 1
    assert stats["verified_claims"] >= 1
    assert stats["verification_rate"] > 0


# ---------------------------------------------------------------------------
# Export and listing tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_report_as_dict(session):
    _, claim = await _make_source_and_claim(session)
    manager = AuditManager(session)
    report = await manager.audit_claim(claim.claim_id)

    exported = await manager.export_report(report.audit_id)
    assert isinstance(exported, dict)
    assert exported["audit_id"] == report.audit_id
    assert exported["report_type"] == "claim"
    assert "findings" in exported
    assert "summary" in exported
    assert "created_at" in exported


@pytest.mark.asyncio
async def test_list_reports_by_type(session):
    _, claim = await _make_source_and_claim(session)
    node = await _make_node(session, "List Reports Node")

    manager = AuditManager(session)
    await manager.audit_claim(claim.claim_id)
    await manager.audit_node(node.node_id)

    claim_reports = await manager.list_reports(report_type="claim")
    node_reports = await manager.list_reports(report_type="node")

    assert all(r.report_type == "claim" for r in claim_reports)
    assert all(r.report_type == "node" for r in node_reports)


@pytest.mark.asyncio
async def test_list_reports_by_node(session):
    node = await _make_node(session, "Node Filter Test")
    manager = AuditManager(session)
    await manager.audit_node(node.node_id)

    reports = await manager.list_reports(node_id=node.node_id)
    assert len(reports) >= 1
    for r in reports:
        assert r.node_id == node.node_id


@pytest.mark.asyncio
async def test_audit_summary_string_populated(session):
    _, claim = await _make_source_and_claim(session)
    manager = AuditManager(session)
    report = await manager.audit_claim(claim.claim_id)

    assert report.summary is not None
    assert len(report.summary) > 10
