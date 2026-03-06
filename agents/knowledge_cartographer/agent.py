"""
Knowledge Cartographer Agent

Responsibilities:
  1. Parse extracted text blocks from registered sources
  2. Extract atomic knowledge claims from text
  3. Identify concepts mentioned in the text
  4. Build knowledge graph nodes and relationships
  5. Assign confidence scores to extracted claims

Outputs:
  claims, concept_nodes, relationships

Note on claim extraction:
  The v1 extractor uses sentence-level heuristics.  In production this module
  would be replaced by (or augmented with) an LLM-based extraction pipeline.
  The interface is identical either way — the database schema does not change.
"""

from __future__ import annotations

import logging
import re
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from core.ingestion.claim_ledger import ClaimLedger
from core.knowledge_graph.graph_manager import KnowledgeGraphManager
from database.schemas.models import ExtractedText, RelationshipType

logger = logging.getLogger(__name__)

# Sentence splitter
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Relationship indicator patterns (verb → RelationshipType)
_REL_PATTERNS = [
    (re.compile(r"\bregulates?\b", re.I), RelationshipType.REGULATES),
    (re.compile(r"\bcontrols?\b", re.I), RelationshipType.CONTROLS),
    (re.compile(r"\bcontains?\b", re.I), RelationshipType.CONTAINS),
    (re.compile(r"\brequires?\b", re.I), RelationshipType.REQUIRES),
    (re.compile(r"\bprecedes?\b|before\b", re.I), RelationshipType.PRECEDES),
    (re.compile(r"\bcauses?\b|results? in\b", re.I), RelationshipType.CAUSES),
    (re.compile(r"\bpart of\b|component of\b", re.I), RelationshipType.PART_OF),
]


class KnowledgeCartographerAgent(BaseAgent):
    """
    Parses source text and builds the claim ledger + knowledge graph.
    """

    name = "knowledge_cartographer"

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.ledger = ClaimLedger(session)
        self.graph = KnowledgeGraphManager(session)

    async def _run(self, payload: dict) -> dict:
        """
        Payload keys:
          source_id (str): ID of the registered source to process
          concept_domain (str, optional): Domain tag for new concepts
          confidence_base (float, optional): Base confidence score (default 0.6)
          max_claims (int, optional): Max claims to extract per run
        """
        source_id = payload["source_id"]
        domain = payload.get("concept_domain")
        confidence_base = float(payload.get("confidence_base", 0.6))
        max_claims = int(payload.get("max_claims", 500))

        # Load extracted text blocks for this source
        stmt = select(ExtractedText).where(ExtractedText.source_id == source_id)
        result = await self.session.execute(stmt)
        text_blocks = result.scalars().all()

        if not text_blocks:
            logger.warning("No extracted text found for source %s", source_id)
            return {"source_id": source_id, "claims_created": 0, "concepts_created": 0}

        claims_created = 0
        concepts_created = 0
        relationships_created = 0

        for block in text_blocks:
            if claims_created >= max_claims:
                break
            sentences = _SENTENCE_RE.split(block.content)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 20:
                    continue
                if claims_created >= max_claims:
                    break

                # Create claim
                citation = f"p.{block.page_number}" if block.page_number else block.section_title
                claim = await self.ledger.create_claim(
                    statement=sentence,
                    source_id=source_id,
                    citation_location=citation,
                    confidence_score=confidence_base,
                    tags=_extract_tags(sentence),
                )
                claims_created += 1

                # Extract concepts and relationships
                rel_hits = _detect_relationships(sentence)
                for parent_name, rel_type, child_name in rel_hits:
                    _, p_new = await self.graph.get_or_create_concept(parent_name, domain=domain)
                    _, c_new = await self.graph.get_or_create_concept(child_name, domain=domain)
                    if p_new:
                        concepts_created += 1
                    if c_new:
                        concepts_created += 1

                    await self.graph.add_relationship(
                        parent_name, rel_type, child_name,
                        source_claim_id=claim.claim_id,
                    )
                    relationships_created += 1

                    # Link claim to parent concept
                    concept = await self.graph.find_concept_by_name(parent_name)
                    if concept and claim.concept_id is None:
                        claim.concept_id = concept.concept_id
                        await self.session.flush()

        logger.info(
            "Cartographer processed source %s: %d claims, %d concepts, %d edges",
            source_id, claims_created, concepts_created, relationships_created,
        )
        return {
            "source_id": source_id,
            "claims_created": claims_created,
            "concepts_created": concepts_created,
            "relationships_created": relationships_created,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_tags(text: str) -> list[str]:
    """Return significant nouns / noun-phrases as tags (simplified)."""
    # In production: use spaCy or NLTK NP chunking
    words = re.findall(r"\b[A-Za-z]{4,}\b", text)
    stop = {"that", "this", "with", "from", "have", "been", "will", "when",
            "then", "they", "their", "which", "also", "some", "more", "than"}
    return list({w.lower() for w in words if w.lower() not in stop})[:10]


def _detect_relationships(sentence: str) -> list[tuple[str, RelationshipType, str]]:
    """
    Detect (subject, relation, object) triples using regex patterns.
    Returns a list of (parent_name, RelationshipType, child_name) tuples.
    """
    results = []
    for pattern, rel_type in _REL_PATTERNS:
        match = pattern.search(sentence)
        if not match:
            continue
        before = sentence[: match.start()].strip()
        after = sentence[match.end() :].strip().rstrip(".")
        if not before or not after:
            continue
        parent = _last_noun_phrase(before)
        child = _first_noun_phrase(after)
        if parent and child and parent != child:
            results.append((parent, rel_type, child))
    return results


def _last_noun_phrase(text: str) -> str:
    """Return the last word sequence before a relation verb (simplified)."""
    words = [w for w in text.split() if len(w) > 2]
    return " ".join(words[-3:]).lower() if words else ""


def _first_noun_phrase(text: str) -> str:
    """Return the first word sequence after a relation verb (simplified)."""
    # Strip leading articles
    text = re.sub(r"^\b(the|a|an|its|their|this|that)\b\s*", "", text, flags=re.I)
    words = [w for w in text.split() if len(w) > 2]
    return " ".join(words[:3]).lower() if words else ""
