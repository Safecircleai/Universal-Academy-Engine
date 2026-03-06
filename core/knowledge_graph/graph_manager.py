"""
Universal Academy Engine — Knowledge Graph Manager

Maps relationships between concepts.  The knowledge graph is the semantic
backbone of the UAE: it lets the Curriculum Architect discover and navigate
related concepts when assembling lessons.

Example relationships:
  thermostat  → regulates   → coolant_flow
  fan_clutch  → controls    → cooling_airflow
  coolant_flow → part_of    → cooling_system
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import Concept, ConceptRelationship, RelationshipType

logger = logging.getLogger(__name__)


class KnowledgeGraphError(Exception):
    """Raised when a graph operation is invalid."""


class KnowledgeGraphManager:
    """
    CRUD operations for :class:`Concept` nodes and
    :class:`ConceptRelationship` edges.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Concept management
    # ------------------------------------------------------------------

    async def get_or_create_concept(
        self,
        name: str,
        *,
        description: str | None = None,
        domain: str | None = None,
        aliases: list[str] | None = None,
    ) -> tuple[Concept, bool]:
        """
        Return an existing concept or create a new one.

        Returns:
            Tuple of (concept, created) where ``created`` is ``True`` when a
            new record was inserted.
        """
        normalized = name.strip().lower()
        stmt = select(Concept).where(Concept.name == normalized)
        result = await self.session.execute(stmt)
        concept = result.scalar_one_or_none()
        if concept:
            return concept, False

        concept = Concept(
            name=normalized,
            description=description,
            domain=domain,
            aliases=aliases or [],
        )
        self.session.add(concept)
        await self.session.flush()
        logger.info("Created concept %r (%s)", normalized, concept.concept_id)
        return concept, True

    async def retrieve_concept(self, concept_id: str) -> Concept:
        stmt = select(Concept).where(Concept.concept_id == concept_id)
        result = await self.session.execute(stmt)
        concept = result.scalar_one_or_none()
        if concept is None:
            raise KnowledgeGraphError(f"Concept not found: {concept_id!r}")
        return concept

    async def find_concept_by_name(self, name: str) -> Optional[Concept]:
        normalized = name.strip().lower()
        stmt = select(Concept).where(Concept.name == normalized)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_concepts(
        self,
        *,
        domain: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Concept]:
        stmt = select(Concept)
        if domain:
            stmt = stmt.where(Concept.domain == domain)
        stmt = stmt.order_by(Concept.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Relationship management
    # ------------------------------------------------------------------

    async def add_relationship(
        self,
        parent_name: str,
        relationship_type: RelationshipType,
        child_name: str,
        *,
        weight: float = 1.0,
        source_claim_id: str | None = None,
    ) -> ConceptRelationship:
        """
        Add a directed relationship between two concepts.
        Concepts are created on demand if they don't exist.
        """
        parent, _ = await self.get_or_create_concept(parent_name)
        child, _ = await self.get_or_create_concept(child_name)

        # Prevent duplicate edges
        existing = await self._find_relationship(parent.concept_id, relationship_type, child.concept_id)
        if existing:
            logger.debug("Relationship already exists: %r→%s→%r", parent.name, relationship_type, child.name)
            return existing

        rel = ConceptRelationship(
            parent_concept_id=parent.concept_id,
            child_concept_id=child.concept_id,
            relationship_type=relationship_type,
            weight=weight,
            source_claim_id=source_claim_id,
        )
        self.session.add(rel)
        await self.session.flush()
        logger.info(
            "Graph edge: %r -[%s]-> %r (claim=%s)",
            parent.name, relationship_type.value, child.name, source_claim_id,
        )
        return rel

    async def get_neighbours(
        self,
        concept_id: str,
        *,
        direction: str = "outgoing",
        relationship_type: RelationshipType | None = None,
    ) -> List[dict]:
        """
        Return neighbouring concept names reachable from a given concept.

        Args:
            direction: ``"outgoing"`` (concept → X), ``"incoming"`` (X → concept),
                       or ``"both"``.
        """
        concept = await self.retrieve_concept(concept_id)

        if direction in ("outgoing", "both"):
            stmt = select(ConceptRelationship).where(
                ConceptRelationship.parent_concept_id == concept_id
            )
            if relationship_type:
                stmt = stmt.where(ConceptRelationship.relationship_type == relationship_type)
            result = await self.session.execute(stmt)
            out_edges = result.scalars().all()
        else:
            out_edges = []

        if direction in ("incoming", "both"):
            stmt = select(ConceptRelationship).where(
                ConceptRelationship.child_concept_id == concept_id
            )
            if relationship_type:
                stmt = stmt.where(ConceptRelationship.relationship_type == relationship_type)
            result = await self.session.execute(stmt)
            in_edges = result.scalars().all()
        else:
            in_edges = []

        neighbours = []
        for edge in out_edges:
            neighbour = await self.retrieve_concept(edge.child_concept_id)
            neighbours.append({
                "concept_id": neighbour.concept_id,
                "name": neighbour.name,
                "direction": "outgoing",
                "relationship_type": edge.relationship_type.value,
                "weight": edge.weight,
            })
        for edge in in_edges:
            neighbour = await self.retrieve_concept(edge.parent_concept_id)
            neighbours.append({
                "concept_id": neighbour.concept_id,
                "name": neighbour.name,
                "direction": "incoming",
                "relationship_type": edge.relationship_type.value,
                "weight": edge.weight,
            })
        return neighbours

    async def get_subgraph(self, root_concept_id: str, max_depth: int = 3) -> dict:
        """
        BFS traversal returning the sub-graph reachable from a root concept.

        Returns:
            dict with ``nodes`` (list of concept dicts) and ``edges`` (list of edge dicts).
        """
        visited: set[str] = set()
        queue = [(root_concept_id, 0)]
        nodes: list[dict] = []
        edges: list[dict] = []

        while queue:
            cid, depth = queue.pop(0)
            if cid in visited or depth > max_depth:
                continue
            visited.add(cid)
            concept = await self.retrieve_concept(cid)
            nodes.append({"concept_id": cid, "name": concept.name, "depth": depth})

            stmt = select(ConceptRelationship).where(
                ConceptRelationship.parent_concept_id == cid
            )
            result = await self.session.execute(stmt)
            for rel in result.scalars().all():
                edges.append({
                    "from": cid,
                    "to": rel.child_concept_id,
                    "type": rel.relationship_type.value,
                    "weight": rel.weight,
                })
                if rel.child_concept_id not in visited:
                    queue.append((rel.child_concept_id, depth + 1))

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _find_relationship(
        self,
        parent_id: str,
        rel_type: RelationshipType,
        child_id: str,
    ) -> Optional[ConceptRelationship]:
        stmt = select(ConceptRelationship).where(
            ConceptRelationship.parent_concept_id == parent_id,
            ConceptRelationship.relationship_type == rel_type,
            ConceptRelationship.child_concept_id == child_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
