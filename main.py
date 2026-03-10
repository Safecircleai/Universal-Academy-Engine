"""
Universal Academy Engine — FastAPI Application Entry Point (v3)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database.connection import init_db
from api.routes import (
    sources, claims, courses, knowledge_graph, verification,
    nodes, attestations, competencies, credentials, audit,
)
from core.federation.transport_server import router as transport_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup."""
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Universal Academy Engine — a governed, source-verified educational "
        "knowledge infrastructure for vocational, civic, and academic learning."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
PREFIX = settings.api_prefix

app.include_router(sources.router, prefix=PREFIX)
app.include_router(claims.router, prefix=PREFIX)
app.include_router(courses.router, prefix=PREFIX)
app.include_router(knowledge_graph.router, prefix=PREFIX)
app.include_router(verification.router, prefix=PREFIX)
# v2 — Federation & hardening
app.include_router(nodes.router, prefix=PREFIX)
app.include_router(attestations.router, prefix=PREFIX)
app.include_router(competencies.router, prefix=PREFIX)
app.include_router(credentials.router, prefix=PREFIX)
app.include_router(audit.router, prefix=PREFIX)

# v3 — Federation Transport (inter-node HTTP)
app.include_router(transport_router, prefix=PREFIX)


@app.get("/", tags=["Health"])
async def root():
    return {
        "name": settings.app_name,
        "version": "3.0.0",
        "status": "running",
        "docs": "/docs",
        "features": [
            "source-registry", "claim-ledger", "knowledge-graph",
            "curriculum-engine", "verification-engine",
            "federation", "cryptographic-attestations",
            "competency-mapping", "credential-issuance", "audit-transparency",
            # v3 additions
            "federation-transport", "jwt-auth", "api-key-auth",
            "key-management", "content-addressed-storage", "agent-workers",
        ],
    }


@app.get("/health", tags=["Health"])
async def health():
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["Health"])
async def readiness():
    """
    Readiness probe — checks database connectivity.
    Returns 200 when the node is ready to serve traffic.
    """
    from database.connection import async_engine
    from sqlalchemy import text
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"Database not ready: {exc}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
