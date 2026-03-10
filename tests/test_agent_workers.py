"""
Tests for UAE v3 Agent Workers

Covers:
  - Structured output parsing and validation
  - BaseWorker governance enforcement (requires_review=True always)
  - Worker outputs are proposals, not verified claims
  - LLM stub mode produces valid structured outputs
  - Invalid LLM output handled gracefully with safe defaults
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio

from agents.structured_outputs import (
    SourceValidationOutput, KnowledgeExtractionOutput, ProposedClaim,
    CurriculumDraftOutput, IntegrityAuditOutput, ConflictProposal,
    parse_agent_output, AgentOutputError
)
from agents.llm_client import LLMClient, LLMResponse


# ------------------------------------------------------------------
# Structured Output Validation
# ------------------------------------------------------------------

class TestStructuredOutputs:
    def test_source_validation_valid(self):
        data = {
            "source_id": "src-001",
            "is_valid": True,
            "trust_tier": "TIER1",
            "validation_notes": "Official documentation",
            "requires_human_review": True,
        }
        result = parse_agent_output(json.dumps(data), SourceValidationOutput)
        assert result.source_id == "src-001"
        assert result.trust_tier == "TIER1"
        assert result.requires_human_review is True

    def test_source_validation_invalid_tier(self):
        data = {
            "source_id": "src-001",
            "is_valid": True,
            "trust_tier": "TIER99",  # invalid
            "validation_notes": "test",
            "requires_human_review": True,
        }
        with pytest.raises(AgentOutputError):
            parse_agent_output(json.dumps(data), SourceValidationOutput)

    def test_proposed_claim_valid(self):
        data = {
            "statement": "Voltage equals current times resistance.",
            "source_id": "src-001",
            "confidence_score": 0.92,
            "requires_human_review": True,
        }
        claim = ProposedClaim(**data)
        assert claim.confidence_score == 0.92
        assert claim.requires_human_review is True

    def test_proposed_claim_empty_statement_raises(self):
        with pytest.raises(Exception):  # Pydantic validation error
            ProposedClaim(
                statement="   ",  # empty after strip
                source_id="src-001",
                confidence_score=0.5,
                requires_human_review=True,
            )

    def test_proposed_claim_confidence_out_of_range(self):
        with pytest.raises(Exception):
            ProposedClaim(
                statement="Valid statement here",
                source_id="src-001",
                confidence_score=1.5,  # > 1.0
                requires_human_review=True,
            )

    def test_knowledge_extraction_output(self):
        data = {
            "source_id": "src-001",
            "proposed_claims": [
                {
                    "statement": "Ohm's Law states V=IR",
                    "source_id": "src-001",
                    "confidence_score": 0.95,
                    "requires_human_review": True,
                }
            ],
            "proposed_concepts": ["Ohm's Law", "Resistance"],
            "extraction_notes": "Clear derivation from source",
            "requires_human_review": True,
        }
        result = parse_agent_output(json.dumps(data), KnowledgeExtractionOutput)
        assert len(result.proposed_claims) == 1
        assert result.requires_human_review is True

    def test_curriculum_draft_requires_claim_ids(self):
        with pytest.raises(Exception):
            from agents.structured_outputs import ProposedLesson
            ProposedLesson(
                title="Lesson without claims",
                content_summary="Content",
                claim_ids=[],  # empty — should fail
                estimated_minutes=30,
                requires_human_review=True,
            )

    def test_integrity_audit_output(self):
        data = {
            "total_claims_checked": 10,
            "proposed_conflicts": [
                {
                    "claim_a_id": "c1",
                    "claim_b_id": "c2",
                    "conflict_description": "Contradictory statements",
                    "severity": "high",
                }
            ],
            "outdated_claim_ids": ["c3"],
            "flagged_claim_ids": ["c4"],
            "summary": "2 issues found",
            "requires_human_review": True,
        }
        result = parse_agent_output(json.dumps(data), IntegrityAuditOutput)
        assert result.total_claims_checked == 10
        assert len(result.proposed_conflicts) == 1
        assert result.proposed_conflicts[0].severity == "high"

    def test_conflict_invalid_severity(self):
        with pytest.raises(Exception):
            ConflictProposal(
                claim_a_id="c1",
                claim_b_id="c2",
                conflict_description="test",
                severity="extreme",  # invalid
            )

    def test_parse_invalid_json(self):
        with pytest.raises(AgentOutputError, match="not valid JSON"):
            parse_agent_output("not json at all {", SourceValidationOutput)

    def test_parse_valid_json_wrong_schema(self):
        data = {"unexpected_field": "value"}
        with pytest.raises(AgentOutputError):
            parse_agent_output(json.dumps(data), SourceValidationOutput)


# ------------------------------------------------------------------
# LLM Client Stub Mode
# ------------------------------------------------------------------

class TestLLMClientStub:
    @pytest.mark.asyncio
    async def test_stub_returns_response(self):
        client = LLMClient(backend="stub")
        response = await client.complete(
            [{"role": "user", "content": "Extract claims from this text."}],
            prompt_type="knowledge_extraction",
        )
        assert isinstance(response.content, str)
        assert response.model_id == "stub"
        assert response.output_hash

    @pytest.mark.asyncio
    async def test_stub_audit_record(self):
        client = LLMClient(backend="stub")
        response = await client.complete(
            [{"role": "user", "content": "test"}],
            prompt_type="source_validation",
        )
        audit = response.to_audit_record()
        assert "model_id" in audit
        assert "output_hash" in audit
        assert "prompt_type" in audit


# ------------------------------------------------------------------
# Worker integration tests (with in-memory DB)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_sentinel_worker_produces_proposal(session):
    """Source sentinel worker must return requires_review=True."""
    from agents.source_sentinel_worker import SourceSentinelWorker
    worker = SourceSentinelWorker(session, llm_client=LLMClient(backend="stub"))

    # Create a minimal node for the governance run
    from database.schemas.models import AcademyNode, NodeType
    node = AcademyNode(
        node_name="test-node-sentinel",
        node_type=NodeType.VOCATIONAL_ACADEMY,
    )
    session.add(node)
    await session.flush()

    result = await worker.run(
        {
            "source_id": "src-001",
            "title": "Test Source",
            "publisher": "Test Publisher",
            "trust_tier": "TIER2",
        },
        input_source_ids=["src-001"],
        prompt_type="source_validation",
    )
    assert result.get("requires_review") is True
    assert result.get("proposal_type") == "source_validation"
    assert "llm_audit" in result


@pytest.mark.asyncio
async def test_knowledge_cartographer_no_claims_on_empty_text(session):
    """Cartographer returns empty proposals on empty text without crashing."""
    from agents.knowledge_cartographer_worker import KnowledgeCartographerWorker
    worker = KnowledgeCartographerWorker(session, llm_client=LLMClient(backend="stub"))

    from database.schemas.models import AcademyNode, NodeType
    node = AcademyNode(node_name="test-node-carto", node_type=NodeType.VOCATIONAL_ACADEMY)
    session.add(node)
    await session.flush()

    result = await worker.run({"source_id": "src-001", "text_content": ""})
    # Should return a routed proposal, not raise
    assert "requires_review" in result


@pytest.mark.asyncio
async def test_integrity_auditor_no_claims(session):
    """Auditor handles no verified claims gracefully."""
    from agents.integrity_auditor_worker import IntegrityAuditorWorker
    worker = IntegrityAuditorWorker(session, llm_client=LLMClient(backend="stub"))

    from database.schemas.models import AcademyNode, NodeType
    node = AcademyNode(node_name="test-node-audit", node_type=NodeType.VOCATIONAL_ACADEMY)
    session.add(node)
    await session.flush()

    result = await worker.run({"claim_ids": []})
    assert result.get("requires_review") is True
