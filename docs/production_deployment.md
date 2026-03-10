# UAE v3 — Production Deployment Guide

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (production required; SQLite for local dev only)
- Docker + Docker Compose (for containerised deployment)

## Quick Start (Local Dev — SQLite)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and edit environment config
cp .env.example .env
# Edit .env — no database changes needed for SQLite dev

# 3. Run migrations (creates tables)
alembic -c database/migrations/alembic.ini upgrade head

# 4. Start the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# API docs: http://localhost:8000/docs
# Health:   http://localhost:8000/health
# Readiness: http://localhost:8000/ready
```

## Production Deployment (PostgreSQL)

### 1. Environment Variables

Set these in your deployment environment (not in `.env` for production):

```bash
# Database
DATABASE_URL=postgresql+asyncpg://uae:PASSWORD@HOST:5432/uae
DATABASE_SYNC_URL=postgresql+psycopg2://uae:PASSWORD@HOST:5432/uae

# Auth
UAE_AUTH_ENABLED=true
UAE_JWT_SECRET=<minimum 32 bytes of random entropy>
UAE_API_KEYS=[{"key":"<raw-key>","role":"admin","name":"admin"},...]

# Node identity
UAE_NODE_ID=my-node-id
UAE_NODE_NAME=My Academy Node
UAE_NODE_URL=https://my-node.example.com

# Key management
UAE_NODE_PRIVATE_KEY=<PEM private key>
UAE_NODE_PUBLIC_KEY=<PEM public key>
UAE_NODE_KEY_ALGORITHM=RSA-SHA256
```

### 2. Run Migrations

```bash
alembic -c database/migrations/alembic.ini upgrade head
```

Always run migrations before starting the application on a new schema version.

### 3. Docker (Single Node)

```bash
docker-compose up -d
```

### 4. Health and Readiness Probes

```
GET /health  → liveness (always 200 if process is up)
GET /ready   → readiness (200 if DB connected, 503 otherwise)
```

Configure your load balancer / orchestrator to use `/ready` for startup probes.

## PostgreSQL Setup

```sql
CREATE USER uae WITH PASSWORD 'your-secure-password';
CREATE DATABASE uae OWNER uae;
GRANT ALL PRIVILEGES ON DATABASE uae TO uae;
```

## Migration Path from SQLite

1. Export existing data from SQLite using the audit export endpoints
2. Set up PostgreSQL instance
3. Update `DATABASE_URL` and `DATABASE_SYNC_URL`
4. Run `alembic upgrade head` against the new PostgreSQL database
5. Re-import data via API or direct SQL import

## Key Checklist for Production

- [ ] PostgreSQL configured and healthy
- [ ] `UAE_JWT_SECRET` is random, min 32 bytes
- [ ] `UAE_NODE_PRIVATE_KEY` is set (not DUMMY)
- [ ] `UAE_AUTH_ENABLED=true`
- [ ] HTTPS enabled at reverse proxy (nginx, Caddy, etc.)
- [ ] Backup strategy for PostgreSQL
- [ ] `/ready` probe configured in load balancer
- [ ] Log aggregation in place (structured logs via uvicorn)
