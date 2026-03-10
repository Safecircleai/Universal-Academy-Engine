"""
UAE v4 — Knowledge Precedence Engine

Enforces the doctrine hierarchy: higher-precedence source types cannot be
overridden by claims from lower-precedence sources without triggering a
constitutional review.

Precedence order (index 0 = highest authority):
  immutable_core > constitutional_doctrine > governance_spec >
  technical_spec > implementation_spec > commentary >
  curriculum > external_reference
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from database.schemas.models import SourceType, ClaimClassification

logger = logging.getLogger(__name__)

# Precedence index: lower value = higher authority
_PRECEDENCE_ORDER = [
    SourceType.IMMUTABLE_CORE,
    SourceType.CONSTITUTIONAL_DOCTRINE,
    SourceType.GOVERNANCE_SPEC,
    SourceType.TECHNICAL_SPEC,
    SourceType.IMPLEMENTATION_SPEC,
    SourceType.COMMENTARY,
    SourceType.CURRICULUM,
    SourceType.EXTERNAL_REFERENCE,
]

# Classifications that require constitutional review when the incoming claim
# comes from a LOWER-precedence source than the claim it interacts with.
_REVIEW_TRIGGERING_CLASSIFICATIONS = {
    ClaimClassification.CONFLICTS_WITH,
    ClaimClassification.SUPERSEDES,
}

# Classifications always requiring review regardless of precedence
_ALWAYS_REVIEW_CLASSIFICATIONS = {
    ClaimClassification.CONFLICTS_WITH,
}


class PrecedenceViolation(Exception):
    """Raised when a lower-precedence claim attempts to override higher doctrine."""


@dataclass
class PrecedenceCheckResult:
    """Result of a precedence check."""
    requires_constitutional_review: bool
    reason: str
    incoming_precedence_level: int      # lower = higher authority
    incumbent_precedence_level: int
    incoming_source_type: SourceType
    incumbent_source_type: Optional[SourceType]
    classification: Optional[ClaimClassification]


class PrecedenceEngine:
    """
    Evaluates whether a new claim respects the knowledge precedence hierarchy.

    Usage::

        engine = PrecedenceEngine()
        result = engine.check(
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.CONFLICTS_WITH,
            incumbent_source_type=SourceType.CONSTITUTIONAL_DOCTRINE,
        )
        if result.requires_constitutional_review:
            # route to constitutional review workflow
    """

    def precedence_level(self, source_type: SourceType) -> int:
        """Return precedence level (0 = highest authority)."""
        try:
            return _PRECEDENCE_ORDER.index(source_type)
        except ValueError:
            return len(_PRECEDENCE_ORDER)  # unknown = lowest

    def is_higher_precedence(self, a: SourceType, b: SourceType) -> bool:
        """Return True if source type `a` has higher (or equal) authority than `b`."""
        return self.precedence_level(a) <= self.precedence_level(b)

    def check(
        self,
        incoming_source_type: SourceType,
        classification: Optional[ClaimClassification] = None,
        incumbent_source_type: Optional[SourceType] = None,
    ) -> PrecedenceCheckResult:
        """
        Determine whether a claim triggers constitutional review.

        Args:
            incoming_source_type: Source type of the new / incoming claim.
            classification: How the claim relates to existing doctrine.
            incumbent_source_type: Source type of the claim being affected
                (if any). Pass None when there is no incumbent.

        Returns:
            PrecedenceCheckResult describing review requirements.
        """
        incoming_level = self.precedence_level(incoming_source_type)
        incumbent_level = (
            self.precedence_level(incumbent_source_type)
            if incumbent_source_type is not None
            else len(_PRECEDENCE_ORDER)
        )

        requires_review = False
        reason = "No constitutional review required."

        # Always review claims that explicitly conflict regardless of precedence
        if classification in _ALWAYS_REVIEW_CLASSIFICATIONS:
            requires_review = True
            reason = (
                f"Classification {classification.value!r} always requires "
                "constitutional review."
            )

        # Lower-precedence source attempting doctrine-altering classification
        elif (
            classification in _REVIEW_TRIGGERING_CLASSIFICATIONS
            and incumbent_source_type is not None
            and incoming_level > incumbent_level
        ):
            requires_review = True
            reason = (
                f"Source type {incoming_source_type.value!r} "
                f"(precedence {incoming_level}) attempts "
                f"{classification.value!r} on "
                f"{incumbent_source_type.value!r} "
                f"(precedence {incumbent_level}). "
                "Lower-precedence sources may not override higher-precedence doctrine."
            )

        # Immutable core cannot be superseded by anything
        elif (
            incumbent_source_type == SourceType.IMMUTABLE_CORE
            and classification in (
                ClaimClassification.SUPERSEDES,
                ClaimClassification.CONFLICTS_WITH,
                ClaimClassification.DEPRECATED_BY,
            )
        ):
            requires_review = True
            reason = (
                "Immutable core doctrine cannot be superseded, deprecated, "
                "or directly conflicted — constitutional review is mandatory."
            )

        logger.debug(
            "Precedence check: %s (%d) %s %s (%d) → review=%s",
            incoming_source_type.value, incoming_level,
            classification.value if classification else "none",
            incumbent_source_type.value if incumbent_source_type else "none",
            incumbent_level,
            requires_review,
        )

        return PrecedenceCheckResult(
            requires_constitutional_review=requires_review,
            reason=reason,
            incoming_precedence_level=incoming_level,
            incumbent_precedence_level=incumbent_level,
            incoming_source_type=incoming_source_type,
            incumbent_source_type=incumbent_source_type,
            classification=classification,
        )

    def get_hierarchy(self) -> list[dict]:
        """Return the full precedence hierarchy as a list of dicts."""
        return [
            {"source_type": st.value, "precedence_level": idx, "authority": "highest" if idx == 0 else "standard"}
            for idx, st in enumerate(_PRECEDENCE_ORDER)
        ]
