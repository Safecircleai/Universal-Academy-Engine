# UAE Academy Framework

## What is an Academy Node?

An Academy Node is a specific deployment of the UAE pipeline configured for a particular domain, audience, and certification standard.

Each Academy Node shares the same knowledge infrastructure but has its own:
- Source document library
- Trust tier assignments
- Claim domain tags
- Course catalogue
- Curriculum standards

---

## Current Academy Nodes

### CFRS Academy (Vocational — Heavy Truck)
- **Domain:** Fleet maintenance, heavy truck systems
- **Audience:** Level 1–3 automotive technicians, fleet managers
- **Standards:** ASE, NATEF, FMCSA
- **Trust Tier 1 Sources:** OEM service manuals, FMCSA regulations
- **Trust Tier 2 Sources:** ASE study materials, NATEF task lists
- **Example Course:** Heavy Truck Cooling Systems

### B4Arts Academy (Creative Education)
- **Domain:** Visual arts, performing arts, music, film
- **Audience:** Artists, educators, creative professionals
- **Standards:** Arts Education standards, professional guild requirements
- **Trust Tier 1 Sources:** Arts council publications, accredited program syllabi

### Governance Training
- **Domain:** Civic governance, public administration, policy
- **Audience:** Elected officials, government staff, civic volunteers
- **Standards:** Government training requirements
- **Trust Tier 1 Sources:** Official government publications, legislative texts

### Charter School Curriculum
- **Domain:** K-12 academic subjects
- **Audience:** Students, teachers
- **Standards:** State academic standards, Common Core
- **Trust Tier 1 Sources:** Approved textbooks, state education department materials

### Professional Certification
- **Domain:** Industry-specific certifications
- **Audience:** Professionals seeking certification
- **Standards:** Industry body requirements
- **Trust Tier 1 Sources:** Certification body publications

---

## Creating a New Academy Node

### Step 1: Define the Domain

Create a directory under `examples/`:
```
examples/your_academy/
├── source_documents/
├── seed_your_academy.py
└── README.md
```

### Step 2: Gather Source Documents

Collect Tier 1 and Tier 2 source documents. Supported formats:
- `.txt`, `.md` — plain text
- `.pdf` — requires PyPDF2
- `.docx` — requires python-docx

### Step 3: Configure Trust Tiers

In your seed script, use the `trust_tier` field when registering sources:
```python
await sentinel.run({
    "title": "...",
    "publisher": "ISO",  # auto-classified as tier1
    "trust_tier": "tier1",  # or explicit override
    ...
})
```

### Step 4: Define Module Structure

Map your curriculum standards to module definitions:
```python
MODULE_DEFS = [
    {"title": "Module 1 — Introduction", "description": "..."},
    {"title": "Module 2 — Core Concepts", "description": "..."},
    ...
]
```

### Step 5: Run the Pipeline

```bash
python -m examples.your_academy.seed_your_academy
```

### Step 6: Human Review

After the pipeline runs:
1. Open the API: `http://localhost:8000/docs`
2. Review draft claims: `GET /api/v1/claims?claim_status=draft`
3. Verify each claim: `POST /api/v1/claims/{id}/verify`
4. Publish the course: `POST /api/v1/courses/{id}/publish`

---

## Curriculum Standards Mapping

Each Academy Node should document how UAE modules map to external standards:

| UAE Module | External Standard | Standard Body |
|------------|------------------|---------------|
| Cooling System Overview | T.002.1 Engine Systems | NATEF |
| Thermostat Operation | T.002.2 Cooling Components | NATEF |
| Fan Clutch Diagnostics | T.002.3 Diagnostic Procedures | NATEF |

This mapping is stored in the course `metadata` field and referenced in learning objectives.

---

## Interoperability

Academy Nodes share the same:
- Claim Ledger (claims can be reused across academies)
- Knowledge Graph (concepts are global)
- Verification Engine
- Governance Manager

Academy Nodes have separate:
- Course catalogues
- Source libraries
- Curriculum standards

This enables cross-domain knowledge reuse — a concept defined in CFRS Academy (e.g., "thermostat") can be linked from Governance Training materials about fleet procurement.
