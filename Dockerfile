FROM python:3.11-slim

# System dependencies for asyncpg and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects $PORT at runtime
ENV API_PORT=8000

CMD ["sh", "-c", "alembic -c database/migrations/alembic.ini upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-$API_PORT}"]
