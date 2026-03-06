"""
UAE API — Source Registry Routes

POST   /sources              Register a new source
GET    /sources              List sources
GET    /sources/{source_id}  Retrieve a source
GET    /sources/{source_id}/validate  Validate a source
DELETE /sources/{source_id}  Deactivate a source
POST   /sources/{source_id}/ingest  Run Source Sentinel pipeline
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agents.source_sentinel import SourceSentinelAgent
from api.models.requests import RegisterSourceRequest, RunAgentRequest
from api.models.responses import PipelineRunResponse, SourceResponse, ValidationResponse
from core.ingestion.source_registry import SourceRegistrationError, SourceRegistry
from database.connection import get_async_session
from database.schemas.models import TrustTier

router = APIRouter(prefix="/sources", tags=["Sources"])


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def register_source(
    body: RegisterSourceRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Register a new trusted knowledge source."""
    registry = SourceRegistry(session)
    # Use a deterministic hash of metadata when no file is provided
    import hashlib, json
    placeholder = json.dumps({
        "title": body.title,
        "publisher": body.publisher,
        "edition": body.edition,
        "source_url": body.source_url,
    }, sort_keys=True).encode()

    try:
        tier = TrustTier(body.trust_tier) if body.trust_tier else TrustTier.TIER3
        source = await registry.register_source(
            title=body.title,
            publisher=body.publisher,
            trust_tier=tier,
            content=placeholder,
            file_path=body.file_path,
            edition=body.edition,
            publication_date=_parse_date(body.publication_date),
            license=body.license,
            source_url=body.source_url,
            language=body.language,
            metadata=body.metadata,
        )
    except SourceRegistrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return SourceResponse.model_validate(source)


@router.get("", response_model=List[SourceResponse])
async def list_sources(
    trust_tier: Optional[str] = None,
    publisher: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    """List registered sources with optional filtering."""
    registry = SourceRegistry(session)
    tier = TrustTier(trust_tier) if trust_tier else None
    sources = await registry.list_sources(
        trust_tier=tier,
        publisher=publisher,
        limit=min(limit, 200),
        offset=offset,
    )
    return [SourceResponse.model_validate(s) for s in sources]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    registry = SourceRegistry(session)
    try:
        source = await registry.retrieve_source(source_id)
    except SourceRegistrationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return SourceResponse.model_validate(source)


@router.get("/{source_id}/validate", response_model=ValidationResponse)
async def validate_source(
    source_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    registry = SourceRegistry(session)
    try:
        report = await registry.validate_source(source_id)
    except SourceRegistrationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ValidationResponse(**report)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_source(
    source_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    registry = SourceRegistry(session)
    try:
        await registry.deactivate_source(source_id)
    except SourceRegistrationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{source_id}/ingest", response_model=PipelineRunResponse)
async def ingest_source(
    source_id: str,
    body: RunAgentRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Run the Knowledge Cartographer on a registered source."""
    from agents.knowledge_cartographer import KnowledgeCartographerAgent
    agent = KnowledgeCartographerAgent(session)
    payload = {"source_id": source_id, **body.payload}
    result = await agent.run(payload)
    return PipelineRunResponse(
        source_id=source_id,
        cartographer_result=result,
        message="Ingestion pipeline completed.",
    )


# ---------------------------------------------------------------------------

def _parse_date(date_str: Optional[str]):
    if not date_str:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return None
