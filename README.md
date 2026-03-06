# Universal Academy Engine (UAE)

> **A governed, source-verified educational knowledge infrastructure for vocational, civic, and academic learning.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is the UAE?

The Universal Academy Engine is not merely a course generator. It is a **verified knowledge pipeline** — a foundational infrastructure that:

- Ingests trusted source documents
- Extracts and stores verifiable knowledge claims
- Builds structured knowledge graphs
- Generates curriculum using **only** verified claims
- Continuously audits and updates learning content

Every piece of curriculum produced by the UAE traces back to a source document. No lesson text can exist without a claim reference. No claim can enter a course until it has been verified.

---

## Supported Academy Nodes

| Academy | Domain |
|---------|--------|
| **CFRS Academy** | Vocational — Heavy Truck / Fleet Maintenance |
| **B4Arts Academy** | Creative Education |
| Governance Training | Civic / Government |
| Charter School Curriculum | K-12 Academic |
| Professional Certification | Industry Credentials |

---

## Architecture Overview

```
Source Document
      │
      ▼
┌─────────────────┐    ┌──────────────────────┐
│  Source Sentinel │───▶│   Source Registry    │
│  (Agent)         │    │   (Module)           │
└─────────────────┘    └──────────────────────┘
      │                          │
      ▼                          ▼
┌──────────────────────┐   ┌────────────────┐
│  Knowledge           │   │  Extracted     │
│  Cartographer (Agent)│   │  Text Blocks   │
└──────────────────────┘   └────────────────┘
      │
      ▼
┌──────────────┐    ┌────────────────────┐
│  Claim Ledger│    │  Knowledge Graph   │
│  (Module)    │    │  (Module)          │
└──────────────┘    └────────────────────┘
      │
   [Human Verification]
      │
      ▼
┌─────────────────────┐
│  Curriculum          │
│  Architect (Agent)   │
└─────────────────────┘
      │
      ▼
┌──────────────────────┐
│  Courses / Modules / │
│  Lessons (all with   │
│  claim citations)    │
└──────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Integrity Auditor  │
│  (Agent)            │
└─────────────────────┘
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Seed the CFRS Academy example

```bash
python -m examples.cfrs_academy.seed_cfrs_academy
```

### 3. Start the API server

```bash
python main.py
# or
uvicorn main:app --reload
```

### 4. Browse the API

Open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive API documentation.

---

## Project Structure

```
universal-academy-engine/
├── main.py                        # FastAPI application entry point
├── config.py                      # Global configuration (env-backed)
├── requirements.txt
│
├── core/
│   ├── ingestion/
│   │   ├── source_registry.py     # Source Registry module
│   │   ├── claim_ledger.py        # Claim Ledger module
│   │   └── text_extractor.py      # Document text extraction
│   ├── knowledge_graph/
│   │   └── graph_manager.py       # Knowledge Graph module
│   ├── curriculum_engine/
│   │   └── curriculum_builder.py  # Curriculum Engine
│   ├── verification/
│   │   └── verification_engine.py # Verification Engine
│   └── governance/
│       └── governance_manager.py  # Human-AI governance
│
├── agents/
│   ├── base_agent.py              # Abstract base agent
│   ├── source_sentinel/           # Document ingestion agent
│   ├── knowledge_cartographer/    # Claim extraction agent
│   ├── curriculum_architect/      # Curriculum assembly agent
│   └── integrity_auditor/         # Integrity monitoring agent
│
├── database/
│   ├── schemas/models.py          # SQLAlchemy ORM models
│   ├── connection.py              # DB connection & session
│   └── migrations/                # Alembic migrations
│
├── api/
│   ├── routes/                    # FastAPI route modules
│   └── models/                    # Pydantic request/response models
│
├── tests/                         # Test suite
│
├── examples/
│   └── cfrs_academy/              # CFRS example academy
│       ├── source_documents/      # Example source manual
│       └── seed_cfrs_academy.py   # Full pipeline seed script
│
└── docs/
    ├── architecture.md
    ├── governance.md
    ├── academy_framework.md
    └── architecture_suggestions.md
```

---

## Core Design Principles

1. **Source-first learning** — Knowledge must originate from verified sources
2. **Claim-based knowledge** — Every factual statement becomes a structured claim
3. **Transparent provenance** — Every lesson traces back to claims and source documents
4. **Versioned knowledge** — All claims maintain full revision history
5. **Human-AI governance** — AI assists; humans have final authority
6. **Extensible node architecture** — Multiple academies, one pipeline
7. **No hallucinated knowledge** — The curriculum generator only assembles verified claims

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/sources` | Register a source document |
| `GET`  | `/api/v1/sources` | List sources |
| `POST` | `/api/v1/sources/{id}/ingest` | Run extraction pipeline |
| `POST` | `/api/v1/claims` | Create a claim |
| `GET`  | `/api/v1/claims` | List claims |
| `POST` | `/api/v1/claims/{id}/verify` | Verify a claim |
| `POST` | `/api/v1/claims/{id}/override` | Human override |
| `POST` | `/api/v1/courses` | Create a course |
| `GET`  | `/api/v1/courses` | List courses |
| `POST` | `/api/v1/concepts` | Create/get concept |
| `GET`  | `/api/v1/concepts/{id}/subgraph` | Knowledge subgraph |
| `POST` | `/api/v1/verification/run` | Run integrity audit |
| `POST` | `/api/v1/agents/curriculum` | Run Curriculum Architect |
| `POST` | `/api/v1/agents/source_sentinel` | Run Source Sentinel |
| `POST` | `/api/v1/agents/integrity_auditor` | Run Integrity Auditor |

---

## Trust Tiers

| Tier | Label | Examples |
|------|-------|---------|
| Tier 1 | Primary Technical Documentation | OEM manuals, NHTSA, SAE, ISO, ANSI |
| Tier 2 | Accredited Training Sources | ASE, NATEF, NCCER, CompTIA |
| Tier 3 | Supplemental Sources | Trade publications, community resources |

---

## Running Tests

```bash
pytest tests/ -v --cov=core --cov=agents --cov=api
```

---

## Contributing

See [docs/governance.md](docs/governance.md) for contribution guidelines and the governance model.

---

## License

MIT — see [LICENSE](LICENSE) for details.
