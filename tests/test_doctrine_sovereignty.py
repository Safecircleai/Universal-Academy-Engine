"""
UAE v4 — Doctrine Sovereignty Layer Tests

Tests cover:
  1. SourceType and ClaimClassification enumerations
  2. PrecedenceEngine hierarchy and review triggers
  3. ConflictDetector detection logic (in-memory, no DB)
  4. InstitutionalArchive write + query + integrity verification
  5. TemporalKnowledgeView time-travel reconstruction
  6. ClaimStatus transitions (constitutional review states)
  7. BaseWorker doctrine safeguards
  8. Roles and permissions for v4 doctrine roles
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from database.schemas.models import (
    ClaimClassification,
    ClaimStatus,
    SourceType,
)
from core.doctrine.precedence_engine import (
    PrecedenceEngine,
    PrecedenceViolation,
    _PRECEDENCE_ORDER,
)
from core.doctrine.conflict_detector import ConflictDetector, DoctrineConflict
from core.auth.roles import Role, has_minimum_role, ROLE_HIERARCHY
from core.auth.permissions import check_permission, PERMISSION_REGISTRY
from core.ingestion.claim_ledger import _assert_transition_valid, ClaimLedgerError


# ===========================================================================
# 1. Enumeration Tests
# ===========================================================================

class TestSourceTypeEnum:
    def test_all_eight_values_exist(self):
        expected = {
            "immutable_core", "constitutional_doctrine", "governance_spec",
            "technical_spec", "implementation_spec", "commentary",
            "curriculum", "external_reference",
        }
        actual = {st.value for st in SourceType}
        assert actual == expected

    def test_values_are_strings(self):
        for st in SourceType:
            assert isinstance(st.value, str)

    def test_str_representation(self):
        assert SourceType.IMMUTABLE_CORE == "immutable_core"
        assert SourceType.EXTERNAL_REFERENCE == "external_reference"


class TestClaimClassificationEnum:
    def test_all_seven_values_exist(self):
        expected = {
            "reinforces", "clarifies", "operationalizes", "extends",
            "conflicts_with", "supersedes", "deprecated_by",
        }
        actual = {cc.value for cc in ClaimClassification}
        assert actual == expected

    def test_conflict_and_supersedes_present(self):
        assert ClaimClassification.CONFLICTS_WITH == "conflicts_with"
        assert ClaimClassification.SUPERSEDES == "supersedes"


class TestConstitutionalClaimStatus:
    def test_three_constitutional_states_exist(self):
        assert ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED == "constitutional_review_required"
        assert ClaimStatus.CONSTITUTIONAL_REVIEW_IN_PROGRESS == "constitutional_review_in_progress"
        assert ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED == "constitutional_decision_recorded"

    def test_original_states_still_exist(self):
        assert ClaimStatus.DRAFT == "draft"
        assert ClaimStatus.VERIFIED == "verified"
        assert ClaimStatus.CONTESTED == "contested"
        assert ClaimStatus.DEPRECATED == "deprecated"


# ===========================================================================
# 2. PrecedenceEngine Tests
# ===========================================================================

class TestPrecedenceEngine:
    def setup_method(self):
        self.engine = PrecedenceEngine()

    def test_precedence_order_length(self):
        assert len(_PRECEDENCE_ORDER) == 8

    def test_immutable_core_is_highest(self):
        assert self.engine.precedence_level(SourceType.IMMUTABLE_CORE) == 0

    def test_external_reference_is_lowest(self):
        assert self.engine.precedence_level(SourceType.EXTERNAL_REFERENCE) == 7

    def test_precedence_ordering(self):
        levels = [self.engine.precedence_level(st) for st in _PRECEDENCE_ORDER]
        assert levels == list(range(len(_PRECEDENCE_ORDER)))

    def test_is_higher_precedence_immutable_vs_curriculum(self):
        assert self.engine.is_higher_precedence(
            SourceType.IMMUTABLE_CORE, SourceType.CURRICULUM
        )

    def test_is_higher_precedence_equal(self):
        assert self.engine.is_higher_precedence(
            SourceType.GOVERNANCE_SPEC, SourceType.GOVERNANCE_SPEC
        )

    def test_lower_does_not_have_higher_precedence(self):
        assert not self.engine.is_higher_precedence(
            SourceType.CURRICULUM, SourceType.IMMUTABLE_CORE
        )

    def test_conflicts_with_always_triggers_review(self):
        result = self.engine.check(
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.CONFLICTS_WITH,
            incumbent_source_type=SourceType.CURRICULUM,
        )
        assert result.requires_constitutional_review is True

    def test_supersedes_lower_on_higher_triggers_review(self):
        result = self.engine.check(
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.SUPERSEDES,
            incumbent_source_type=SourceType.CONSTITUTIONAL_DOCTRINE,
        )
        assert result.requires_constitutional_review is True

    def test_supersedes_higher_on_lower_no_review(self):
        result = self.engine.check(
            incoming_source_type=SourceType.CONSTITUTIONAL_DOCTRINE,
            classification=ClaimClassification.SUPERSEDES,
            incumbent_source_type=SourceType.CURRICULUM,
        )
        assert result.requires_constitutional_review is False

    def test_reinforces_no_review(self):
        result = self.engine.check(
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.REINFORCES,
            incumbent_source_type=SourceType.IMMUTABLE_CORE,
        )
        assert result.requires_constitutional_review is False

    def test_immutable_core_superseded_triggers_review(self):
        result = self.engine.check(
            incoming_source_type=SourceType.GOVERNANCE_SPEC,
            classification=ClaimClassification.SUPERSEDES,
            incumbent_source_type=SourceType.IMMUTABLE_CORE,
        )
        assert result.requires_constitutional_review is True

    def test_no_classification_no_review(self):
        result = self.engine.check(
            incoming_source_type=SourceType.CURRICULUM,
            classification=None,
        )
        assert result.requires_constitutional_review is False

    def test_get_hierarchy_returns_all_levels(self):
        hierarchy = self.engine.get_hierarchy()
        assert len(hierarchy) == 8
        assert hierarchy[0]["source_type"] == "immutable_core"
        assert hierarchy[0]["authority"] == "highest"

    def test_precedence_result_fields(self):
        result = self.engine.check(
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.CONFLICTS_WITH,
            incumbent_source_type=SourceType.GOVERNANCE_SPEC,
        )
        assert result.incoming_source_type == SourceType.CURRICULUM
        assert result.incoming_precedence_level == 6
        assert result.incumbent_precedence_level == 2


# ===========================================================================
# 3. Conflict Detector Tests (pure logic, mocked DB)
# ===========================================================================

class TestConflictDetector:
    """Tests that don't need a real database session."""

    def _make_mock_session(self):
        session = AsyncMock()
        # Mock execute to return empty results by default
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        return session

    @pytest.mark.asyncio
    async def test_conflicts_with_always_detected(self):
        session = self._make_mock_session()
        detector = ConflictDetector(session)
        conflicts = await detector.detect(
            claim_id="claim-001",
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.CONFLICTS_WITH,
            statement="Test claim",
        )
        assert len(conflicts) >= 1
        assert any(c.requires_constitutional_review for c in conflicts)

    @pytest.mark.asyncio
    async def test_reinforces_no_conflict(self):
        session = self._make_mock_session()
        detector = ConflictDetector(session)
        conflicts = await detector.detect(
            claim_id="claim-001",
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.REINFORCES,
            statement="Test claim",
        )
        assert all(not c.requires_constitutional_review for c in conflicts)

    @pytest.mark.asyncio
    async def test_federation_import_cross_node_flag(self):
        session = self._make_mock_session()
        detector = ConflictDetector(session)
        conflicts = await detector.check_federation_import(
            incoming_claim_id="claim-001",
            incoming_source_type=SourceType.GOVERNANCE_SPEC,
            classification=ClaimClassification.SUPERSEDES,
            origin_node_id="node-a",
            local_node_id="node-b",
        )
        cross_node = [c for c in conflicts if c.conflict_type == "cross_node"]
        assert len(cross_node) == 1
        assert cross_node[0].requires_constitutional_review is True

    @pytest.mark.asyncio
    async def test_conflict_has_required_fields(self):
        session = self._make_mock_session()
        detector = ConflictDetector(session)
        conflicts = await detector.detect(
            claim_id="claim-002",
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.CONFLICTS_WITH,
            statement="Test",
        )
        for conflict in conflicts:
            assert conflict.conflict_id
            assert conflict.incoming_claim_id == "claim-002"
            assert conflict.conflict_type
            assert conflict.severity in ("critical", "major", "minor")
            assert isinstance(conflict.requires_constitutional_review, bool)

    @pytest.mark.asyncio
    async def test_supersedes_lower_incumbent_no_conflict(self):
        """Higher-precedence superseding lower — no constitutional conflict."""
        session = self._make_mock_session()
        # Simulate incumbent source type = curriculum (lower)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = SourceType.CURRICULUM
        session.execute = AsyncMock(return_value=mock_result)

        detector = ConflictDetector(session)
        conflicts = await detector.detect(
            claim_id="claim-003",
            incoming_source_type=SourceType.GOVERNANCE_SPEC,
            classification=ClaimClassification.SUPERSEDES,
            statement="Test",
            incumbent_claim_ids=["incumbent-001"],
        )
        # No constitutional review needed (higher precedence supersedes lower)
        review_required = [c for c in conflicts if c.requires_constitutional_review
                           and c.conflict_type == "precedence_violation"]
        assert len(review_required) == 0


# ===========================================================================
# 4. InstitutionalArchive Tests
# ===========================================================================

class TestInstitutionalArchive:
    @pytest.mark.asyncio
    async def test_record_creates_entry(self):
        from core.memory.institutional_archive import InstitutionalArchive, ArchiveError

        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        archive = InstitutionalArchive(session)
        entry = await archive.record(
            event_type="claim_status_transition",
            subject_id="claim-001",
            subject_type="claim",
            event_summary="Claim transitioned draft → constitutional_review_required",
            preceding_state={"status": "draft"},
            resulting_state={"status": "constitutional_review_required"},
            actor_id="reviewer@node",
        )

        assert entry.event_type == "claim_status_transition"
        assert entry.subject_id == "claim-001"
        assert entry.content_hash is not None
        session.add.assert_called_once()
        session.flush.assert_called_once()

    def test_hash_entry_deterministic(self):
        from core.memory.institutional_archive import InstitutionalArchive

        h1 = InstitutionalArchive._hash_entry(
            "event_type", "subj-001", "summary",
            {"before": "draft"}, {"after": "verified"}
        )
        h2 = InstitutionalArchive._hash_entry(
            "event_type", "subj-001", "summary",
            {"before": "draft"}, {"after": "verified"}
        )
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_entry_different_when_content_differs(self):
        from core.memory.institutional_archive import InstitutionalArchive

        h1 = InstitutionalArchive._hash_entry("a", "b", "c", None, None)
        h2 = InstitutionalArchive._hash_entry("a", "b", "different", None, None)
        assert h1 != h2

    @pytest.mark.asyncio
    async def test_record_requires_event_type(self):
        from core.memory.institutional_archive import InstitutionalArchive, ArchiveError

        archive = InstitutionalArchive(AsyncMock())
        with pytest.raises(ArchiveError):
            await archive.record(
                event_type="",
                subject_id="x",
                subject_type="claim",
                event_summary="summary",
            )

    @pytest.mark.asyncio
    async def test_record_requires_subject_id(self):
        from core.memory.institutional_archive import InstitutionalArchive, ArchiveError

        archive = InstitutionalArchive(AsyncMock())
        with pytest.raises(ArchiveError):
            await archive.record(
                event_type="transition",
                subject_id="",
                subject_type="claim",
                event_summary="summary",
            )


# ===========================================================================
# 5. ClaimStatus Transitions Tests
# ===========================================================================

class TestConstitutionalReviewTransitions:
    def test_draft_can_go_to_constitutional_review_required(self):
        _assert_transition_valid(
            ClaimStatus.DRAFT,
            ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
        )  # Should not raise

    def test_verified_can_go_to_constitutional_review_required(self):
        _assert_transition_valid(
            ClaimStatus.VERIFIED,
            ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
        )

    def test_contested_can_go_to_constitutional_review_required(self):
        _assert_transition_valid(
            ClaimStatus.CONTESTED,
            ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
        )

    def test_constitutional_review_required_to_in_progress(self):
        _assert_transition_valid(
            ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
            ClaimStatus.CONSTITUTIONAL_REVIEW_IN_PROGRESS,
        )

    def test_constitutional_review_in_progress_to_decision_recorded(self):
        _assert_transition_valid(
            ClaimStatus.CONSTITUTIONAL_REVIEW_IN_PROGRESS,
            ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED,
        )

    def test_constitutional_decision_recorded_to_verified(self):
        _assert_transition_valid(
            ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED,
            ClaimStatus.VERIFIED,
        )

    def test_constitutional_decision_recorded_to_deprecated(self):
        _assert_transition_valid(
            ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED,
            ClaimStatus.DEPRECATED,
        )

    def test_invalid_skip_from_required_to_decision_recorded(self):
        with pytest.raises(ClaimLedgerError):
            _assert_transition_valid(
                ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
                ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED,
            )

    def test_deprecated_cannot_go_to_constitutional_review(self):
        with pytest.raises(ClaimLedgerError):
            _assert_transition_valid(
                ClaimStatus.DEPRECATED,
                ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
            )

    def test_constitutional_in_progress_cannot_go_to_verified_directly(self):
        with pytest.raises(ClaimLedgerError):
            _assert_transition_valid(
                ClaimStatus.CONSTITUTIONAL_REVIEW_IN_PROGRESS,
                ClaimStatus.VERIFIED,
            )


# ===========================================================================
# 6. BaseWorker Doctrine Safeguards Tests
# ===========================================================================

class TestBaseWorkerDoctrineSafeguards:
    def _make_worker(self):
        from agents.base_worker import BaseWorker

        class ConcreteWorker(BaseWorker):
            name = "test_worker"

            async def _run_work(self, payload: dict) -> dict:
                return {"result": "ok"}

        mock_session = AsyncMock()
        mock_governance = MagicMock()
        mock_governance.start_agent_run = AsyncMock(return_value=MagicMock(
            run_id="run-001", model_id=None, prompt_type=None,
            input_source_ids=None, requires_review=True, output_hash=None,
        ))
        mock_governance.complete_agent_run = AsyncMock()
        mock_session.flush = AsyncMock()

        worker = ConcreteWorker(mock_session)
        worker.governance = mock_governance
        return worker

    def test_conflicts_with_triggers_constitutional_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test claim"}
        result = worker._check_doctrine_safeguards(
            proposal,
            claim_classification="conflicts_with",
        )
        assert result["requires_constitutional_review"] is True
        assert "doctrine_review_reason" in result

    def test_supersedes_triggers_constitutional_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test claim"}
        result = worker._check_doctrine_safeguards(
            proposal,
            claim_classification="supersedes",
        )
        assert result["requires_constitutional_review"] is True

    def test_reinforces_no_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test claim"}
        result = worker._check_doctrine_safeguards(
            proposal,
            claim_classification="reinforces",
        )
        assert result["requires_constitutional_review"] is False

    def test_immutable_core_source_type_triggers_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test claim"}
        result = worker._check_doctrine_safeguards(
            proposal,
            source_type="immutable_core",
        )
        assert result["requires_constitutional_review"] is True

    def test_constitutional_doctrine_source_type_triggers_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test claim"}
        result = worker._check_doctrine_safeguards(
            proposal,
            source_type="constitutional_doctrine",
        )
        assert result["requires_constitutional_review"] is True

    def test_curriculum_source_type_no_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test claim"}
        result = worker._check_doctrine_safeguards(
            proposal,
            source_type="curriculum",
        )
        assert result["requires_constitutional_review"] is False

    def test_unknown_classification_no_crash(self):
        worker = self._make_worker()
        proposal = {"statement": "Test"}
        result = worker._check_doctrine_safeguards(
            proposal,
            claim_classification="unknown_future_value",
        )
        assert "requires_constitutional_review" in result

    def test_no_args_no_review(self):
        worker = self._make_worker()
        proposal = {"statement": "Test"}
        result = worker._check_doctrine_safeguards(proposal)
        assert result["requires_constitutional_review"] is False


# ===========================================================================
# 7. Roles and Permissions for v4
# ===========================================================================

class TestV4Roles:
    def test_doctrine_steward_in_hierarchy(self):
        assert Role.DOCTRINE_STEWARD in ROLE_HIERARCHY

    def test_constitutional_reviewer_in_hierarchy(self):
        assert Role.CONSTITUTIONAL_REVIEWER in ROLE_HIERARCHY

    def test_governance_council_in_hierarchy(self):
        assert Role.GOVERNANCE_COUNCIL in ROLE_HIERARCHY

    def test_governance_council_outranks_constitutional_reviewer(self):
        assert has_minimum_role(Role.GOVERNANCE_COUNCIL, Role.CONSTITUTIONAL_REVIEWER)

    def test_constitutional_reviewer_outranks_doctrine_steward(self):
        assert has_minimum_role(Role.CONSTITUTIONAL_REVIEWER, Role.DOCTRINE_STEWARD)

    def test_doctrine_steward_outranks_curriculum_operator(self):
        assert has_minimum_role(Role.DOCTRINE_STEWARD, Role.CURRICULUM_OPERATOR)

    def test_admin_has_all_doctrine_roles(self):
        assert has_minimum_role(Role.ADMIN, Role.GOVERNANCE_COUNCIL)
        assert has_minimum_role(Role.ADMIN, Role.CONSTITUTIONAL_REVIEWER)
        assert has_minimum_role(Role.ADMIN, Role.DOCTRINE_STEWARD)

    def test_reviewer_does_not_have_doctrine_steward(self):
        assert not has_minimum_role(Role.REVIEWER, Role.DOCTRINE_STEWARD)


class TestV4Permissions:
    def test_doctrine_source_type_classify_requires_doctrine_steward(self):
        assert check_permission(Role.DOCTRINE_STEWARD, "doctrine:source_type:classify")
        assert not check_permission(Role.CURRICULUM_OPERATOR, "doctrine:source_type:classify")

    def test_doctrine_constitutional_review_conduct_requires_reviewer(self):
        assert check_permission(Role.CONSTITUTIONAL_REVIEWER, "doctrine:constitutional_review:conduct")
        assert not check_permission(Role.DOCTRINE_STEWARD, "doctrine:constitutional_review:conduct")

    def test_doctrine_governance_decision_create_requires_council(self):
        assert check_permission(Role.GOVERNANCE_COUNCIL, "doctrine:governance_decision:create")
        assert not check_permission(Role.CONSTITUTIONAL_REVIEWER, "doctrine:governance_decision:create")

    def test_doctrine_archive_read_requires_auditor(self):
        assert check_permission(Role.AUDITOR, "doctrine:archive:read")
        assert not check_permission(Role.READ_ONLY, "doctrine:archive:read")

    def test_doctrine_precedence_override_requires_council(self):
        assert check_permission(Role.GOVERNANCE_COUNCIL, "doctrine:precedence:override")
        assert not check_permission(Role.CONSTITUTIONAL_REVIEWER, "doctrine:precedence:override")

    def test_doctrine_source_type_read_is_public(self):
        assert check_permission(Role.READ_ONLY, "doctrine:source_type:read")

    def test_admin_has_all_doctrine_permissions(self):
        doctrine_perms = [k for k in PERMISSION_REGISTRY if k.startswith("doctrine:")]
        for perm in doctrine_perms:
            assert check_permission(Role.ADMIN, perm), f"Admin missing permission: {perm}"


# ===========================================================================
# 8. TemporalKnowledgeView Tests
# ===========================================================================

class TestTemporalKnowledgeView:
    @pytest.mark.asyncio
    async def test_snapshot_summary_fields(self):
        from core.memory.temporal_views import TemporalKnowledgeSnapshot

        snapshot = TemporalKnowledgeSnapshot(
            as_of=datetime(2024, 1, 1),
            node_id="node-a",
            total_claims=10,
        )
        summary = snapshot.summary
        assert summary["as_of"] == "2024-01-01T00:00:00"
        assert summary["node_id"] == "node-a"
        assert summary["total_claims"] == 10
        assert "verified_count" in summary
        assert "contested_count" in summary

    def test_temporal_claim_state_fields(self):
        from core.memory.temporal_views import TemporalClaimState

        state = TemporalClaimState(
            claim_id="c-001",
            claim_number="CLM000001",
            statement="Test",
            status="verified",
            confidence_score=0.9,
            source_id="src-001",
            source_type="governance_spec",
            claim_classification="reinforces",
            requires_constitutional_review=False,
            version=2,
            as_of=datetime(2024, 6, 1),
        )
        assert state.status == "verified"
        assert state.source_type == "governance_spec"
        assert state.requires_constitutional_review is False

    @pytest.mark.asyncio
    async def test_get_claim_state_at_none_for_future_claim(self):
        from core.memory.temporal_views import TemporalKnowledgeView

        future_time = datetime(2030, 1, 1)
        past_time = datetime(2020, 1, 1)

        mock_claim = MagicMock()
        mock_claim.created_at = future_time  # created in the future

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_claim
        session.execute = AsyncMock(return_value=mock_result)

        view = TemporalKnowledgeView(session)
        state = await view.get_claim_state_at("claim-001", past_time)
        assert state is None  # claim didn't exist yet at past_time
