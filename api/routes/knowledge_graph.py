"""
UAE API — Knowledge Graph Routes

POST   /concepts                              Create or get concept
GET    /concepts                              List concepts
GET    /concepts/{concept_id}                 Retrieve concept
GET    /concepts/{concept_id}/neighbours      Get neighbours
GET    /concepts/{concept_id}/subgraph        Get sub-graph
POST   /concepts/relationships                Add relationship
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.requests import AddRelationshipRequest, CreateConceptRequest
from api.models.responses import ConceptResponse, SubgraphResponse
from core.knowledge_graph.graph_manager import KnowledgeGraphError, KnowledgeGraphManager
from database.connection import get_async_session
from database.schemas.models import RelationshipType

router = APIRouter(prefix="/concepts", tags=["Knowledge Graph"])


@router.post("", response_model=ConceptResponse, status_code=status.HTTP_201_CREATED)
async def create_concept(
    body: CreateConceptRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Create a concept node (or return existing if name already exists)."""
    manager = KnowledgeGraphManager(session)
    concept, _ = await manager.get_or_create_concept(
        body.name,
        description=body.description,
        domain=body.domain,
        aliases=body.aliases,
    )
    return ConceptResponse.model_validate(concept)


@router.get("", response_model=List[ConceptResponse])
async def list_concepts(
    domain: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    manager = KnowledgeGraphManager(session)
    concepts = await manager.list_concepts(domain=domain, limit=min(limit, 200), offset=offset)
    return [ConceptResponse.model_validate(c) for c in concepts]


@router.get("/{concept_id}", response_model=ConceptResponse)
async def get_concept(
    concept_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = KnowledgeGraphManager(session)
    try:
        concept = await manager.retrieve_concept(concept_id)
    except KnowledgeGraphError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ConceptResponse.model_validate(concept)


@router.get("/{concept_id}/neighbours")
async def get_neighbours(
    concept_id: str,
    direction: str = "outgoing",
    relationship_type: Optional[str] = None,
    session: AsyncSession = Depends(get_async_session),
):
    manager = KnowledgeGraphManager(session)
    try:
        rel_type = RelationshipType(relationship_type) if relationship_type else None
        neighbours = await manager.get_neighbours(
            concept_id, direction=direction, relationship_type=rel_type
        )
    except KnowledgeGraphError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"concept_id": concept_id, "neighbours": neighbours}


@router.get("/{concept_id}/subgraph", response_model=SubgraphResponse)
async def get_subgraph(
    concept_id: str,
    max_depth: int = 3,
    session: AsyncSession = Depends(get_async_session),
):
    manager = KnowledgeGraphManager(session)
    try:
        subgraph = await manager.get_subgraph(concept_id, max_depth=max_depth)
    except KnowledgeGraphError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return SubgraphResponse(**subgraph)


@router.post("/relationships", status_code=status.HTTP_201_CREATED)
async def add_relationship(
    body: AddRelationshipRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = KnowledgeGraphManager(session)
    try:
        rel = await manager.add_relationship(
            body.parent_name, body.relationship_type, body.child_name,
            weight=body.weight,
            source_claim_id=body.source_claim_id,
        )
    except (ValueError, KnowledgeGraphError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "relationship_id": rel.relationship_id,
        "parent_concept_id": rel.parent_concept_id,
        "child_concept_id": rel.child_concept_id,
        "relationship_type": rel.relationship_type.value,
        "weight": rel.weight,
    }
