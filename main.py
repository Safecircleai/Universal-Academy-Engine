"""
Universal Academy Engine — FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database.connection import init_db
from api.routes import sources, claims, courses, knowledge_graph, verification


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


@app.get("/", tags=["Health"])
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
