FROM python:3.11-slim

# System dependencies for asyncpg, psycopg2, and health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create storage directory for content-addressed objects
RUN mkdir -p /app/storage

# Railway injects $PORT at runtime
ENV API_PORT=8000

# Health check (Docker native)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-$API_PORT}/health || exit 1

# Startup: run Alembic migrations then start uvicorn
CMD ["sh", "-c", "alembic -c database/migrations/alembic.ini upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-$API_PORT}"]
