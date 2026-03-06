"""Tests for the Knowledge Graph module."""

import pytest
from core.knowledge_graph.graph_manager import KnowledgeGraphManager, KnowledgeGraphError
from database.schemas.models import RelationshipType


@pytest.mark.asyncio
async def test_get_or_create_concept_new(session):
    manager = KnowledgeGraphManager(session)
    concept, created = await manager.get_or_create_concept("thermostat")
    assert created is True
    assert concept.name == "thermostat"
    assert concept.concept_id is not None


@pytest.mark.asyncio
async def test_get_or_create_concept_existing(session):
    manager = KnowledgeGraphManager(session)
    c1, _ = await manager.get_or_create_concept("coolant flow")
    c2, created = await manager.get_or_create_concept("Coolant Flow")  # case-insensitive
    assert created is False
    assert c1.concept_id == c2.concept_id


@pytest.mark.asyncio
async def test_add_relationship(session):
    manager = KnowledgeGraphManager(session)
    rel = await manager.add_relationship(
        "thermostat",
        RelationshipType.REGULATES,
        "coolant flow",
    )
    assert rel.relationship_id is not None
    assert rel.relationship_type == RelationshipType.REGULATES


@pytest.mark.asyncio
async def test_add_relationship_idempotent(session):
    """Adding the same relationship twice returns the existing record."""
    manager = KnowledgeGraphManager(session)
    r1 = await manager.add_relationship("fan clutch", RelationshipType.CONTROLS, "cooling airflow")
    r2 = await manager.add_relationship("fan clutch", RelationshipType.CONTROLS, "cooling airflow")
    assert r1.relationship_id == r2.relationship_id


@pytest.mark.asyncio
async def test_get_neighbours_outgoing(session):
    manager = KnowledgeGraphManager(session)
    await manager.add_relationship("thermostat", RelationshipType.REGULATES, "coolant flow")
    await manager.add_relationship("thermostat", RelationshipType.PART_OF, "cooling system")

    concept, _ = await manager.get_or_create_concept("thermostat")
    neighbours = await manager.get_neighbours(concept.concept_id, direction="outgoing")

    neighbour_names = [n["name"] for n in neighbours]
    assert "coolant flow" in neighbour_names
    assert "cooling system" in neighbour_names


@pytest.mark.asyncio
async def test_get_subgraph(session):
    manager = KnowledgeGraphManager(session)
    await manager.add_relationship("cooling system", RelationshipType.CONTAINS, "thermostat")
    await manager.add_relationship("cooling system", RelationshipType.CONTAINS, "fan clutch")
    await manager.add_relationship("thermostat", RelationshipType.REGULATES, "coolant flow")

    root, _ = await manager.get_or_create_concept("cooling system")
    subgraph = await manager.get_subgraph(root.concept_id, max_depth=2)

    node_names = [n["name"] for n in subgraph["nodes"]]
    assert "cooling system" in node_names
    assert "thermostat" in node_names
    assert "fan clutch" in node_names
    assert "coolant flow" in node_names


@pytest.mark.asyncio
async def test_retrieve_concept_not_found(session):
    manager = KnowledgeGraphManager(session)
    with pytest.raises(KnowledgeGraphError, match="Concept not found"):
        await manager.retrieve_concept("non-existent-id")


@pytest.mark.asyncio
async def test_find_concept_by_name(session):
    manager = KnowledgeGraphManager(session)
    await manager.get_or_create_concept("water pump", domain="cooling")
    found = await manager.find_concept_by_name("water pump")
    assert found is not None
    assert found.domain == "cooling"


@pytest.mark.asyncio
async def test_list_concepts_by_domain(session):
    manager = KnowledgeGraphManager(session)
    await manager.get_or_create_concept("concept_a", domain="domain_x")
    await manager.get_or_create_concept("concept_b", domain="domain_x")
    await manager.get_or_create_concept("concept_c", domain="domain_y")

    domain_x = await manager.list_concepts(domain="domain_x")
    assert len(domain_x) == 2
    assert all(c.domain == "domain_x" for c in domain_x)
