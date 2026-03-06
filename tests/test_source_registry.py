"""Tests for the Source Registry module."""

import pytest
from core.ingestion.source_registry import SourceRegistry, SourceRegistrationError
from database.schemas.models import TrustTier


@pytest.mark.asyncio
async def test_register_source_success(session):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Test Manual",
        publisher="Test Publisher",
        trust_tier=TrustTier.TIER1,
        content=b"Sample document content",
    )
    assert source.source_id is not None
    assert source.title == "Test Manual"
    assert source.publisher == "Test Publisher"
    assert source.trust_tier == TrustTier.TIER1
    assert source.document_hash is not None
    assert source.is_active is True


@pytest.mark.asyncio
async def test_register_source_requires_content_or_path(session):
    registry = SourceRegistry(session)
    with pytest.raises(SourceRegistrationError, match="Either 'content' or 'file_path'"):
        await registry.register_source(
            title="Test",
            publisher="Test",
            trust_tier=TrustTier.TIER3,
        )


@pytest.mark.asyncio
async def test_register_source_idempotent_by_hash(session):
    """Registering the same document twice returns the existing record."""
    registry = SourceRegistry(session)
    content = b"Identical document"
    s1 = await registry.register_source(
        title="Doc A", publisher="Pub", trust_tier=TrustTier.TIER2, content=content
    )
    s2 = await registry.register_source(
        title="Doc A (duplicate)", publisher="Pub", trust_tier=TrustTier.TIER2, content=content
    )
    assert s1.source_id == s2.source_id


@pytest.mark.asyncio
async def test_validate_source(session):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Valid Source",
        publisher="Valid Publisher",
        trust_tier=TrustTier.TIER1,
        content=b"content",
    )
    report = await registry.validate_source(source.source_id)
    assert report["valid"] is True
    assert report["issues"] == []


@pytest.mark.asyncio
async def test_retrieve_source(session):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="Retrievable Source",
        publisher="Publisher",
        trust_tier=TrustTier.TIER3,
        content=b"data",
    )
    retrieved = await registry.retrieve_source(source.source_id)
    assert retrieved.source_id == source.source_id


@pytest.mark.asyncio
async def test_retrieve_source_not_found(session):
    registry = SourceRegistry(session)
    with pytest.raises(SourceRegistrationError, match="Source not found"):
        await registry.retrieve_source("non-existent-id")


@pytest.mark.asyncio
async def test_list_sources(session):
    registry = SourceRegistry(session)
    for i in range(3):
        await registry.register_source(
            title=f"Source {i}",
            publisher="Publisher",
            trust_tier=TrustTier.TIER2,
            content=f"content {i}".encode(),
        )
    sources = await registry.list_sources()
    assert len(sources) >= 3


@pytest.mark.asyncio
async def test_list_sources_filter_by_tier(session):
    registry = SourceRegistry(session)
    await registry.register_source(
        title="Tier1 Source", publisher="Pub", trust_tier=TrustTier.TIER1, content=b"t1"
    )
    await registry.register_source(
        title="Tier3 Source", publisher="Pub", trust_tier=TrustTier.TIER3, content=b"t3"
    )
    tier1_sources = await registry.list_sources(trust_tier=TrustTier.TIER1)
    assert all(s.trust_tier == TrustTier.TIER1 for s in tier1_sources)


@pytest.mark.asyncio
async def test_deactivate_source(session):
    registry = SourceRegistry(session)
    source = await registry.register_source(
        title="To Deactivate", publisher="Pub", trust_tier=TrustTier.TIER3, content=b"deact"
    )
    await registry.deactivate_source(source.source_id)
    # Active sources should not include it
    active = await registry.list_sources(is_active=True)
    active_ids = [s.source_id for s in active]
    assert source.source_id not in active_ids
