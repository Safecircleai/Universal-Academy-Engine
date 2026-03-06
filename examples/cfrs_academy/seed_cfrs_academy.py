"""
CFRS Academy — Seed Script

Populates the UAE database with the Heavy Truck Cooling Systems course.
Runs the full pipeline:
  1. Source Sentinel — ingests the technical manual
  2. Knowledge Cartographer — extracts claims and builds the knowledge graph
  3. Manual claim verification (simulates human review)
  4. Curriculum Architect — builds the course from verified claims
  5. Integrity Auditor — initial audit pass

Usage:
  python -m examples.cfrs_academy.seed_cfrs_academy
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure repo root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from database.connection import init_db, AsyncSessionLocal
from agents.source_sentinel import SourceSentinelAgent
from agents.knowledge_cartographer import KnowledgeCartographerAgent
from agents.curriculum_architect import CurriculumArchitectAgent
from agents.integrity_auditor import IntegrityAuditorAgent
from core.ingestion.claim_ledger import ClaimLedger
from core.knowledge_graph.graph_manager import KnowledgeGraphManager
from database.schemas.models import ClaimStatus, RelationshipType

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("cfrs_seed")

MANUAL_PATH = Path(__file__).parent / "source_documents" / "heavy_truck_cooling_manual.txt"

# ---------------------------------------------------------------------------
# Manual knowledge-graph relationships (from domain expertise)
# ---------------------------------------------------------------------------
EXPERT_RELATIONSHIPS = [
    ("thermostat", RelationshipType.REGULATES, "coolant flow"),
    ("fan clutch", RelationshipType.CONTROLS, "cooling airflow"),
    ("water pump", RelationshipType.CONTROLS, "coolant flow"),
    ("coolant flow", RelationshipType.PART_OF, "cooling system"),
    ("radiator", RelationshipType.CONTAINS, "coolant"),
    ("thermostat", RelationshipType.PART_OF, "cooling system"),
    ("fan clutch", RelationshipType.PART_OF, "cooling system"),
    ("overheating", RelationshipType.CAUSES, "engine damage"),
    ("stuck thermostat", RelationshipType.CAUSES, "overheating"),
    ("freewheeling fan clutch", RelationshipType.CAUSES, "idle overheating"),
    ("coolant level", RelationshipType.REQUIRES, "regular inspection"),
]

# ---------------------------------------------------------------------------
# Module definitions for the CFRS course
# ---------------------------------------------------------------------------
MODULE_DEFS = [
    {
        "title": "Module 1 — Cooling System Overview",
        "description": "Introduction to the heavy truck cooling system architecture.",
        "section_keywords": ["cooling system", "coolant", "overview"],
    },
    {
        "title": "Module 2 — Thermostat Operation",
        "description": "How the thermostat regulates coolant flow and engine temperature.",
        "section_keywords": ["thermostat", "temperature", "wax element"],
    },
    {
        "title": "Module 3 — Fan Clutch Diagnostics",
        "description": "Diagnosing and testing fan clutch failures.",
        "section_keywords": ["fan clutch", "viscous", "silicone", "diagnostic"],
    },
    {
        "title": "Module 4 — Failure Case Studies",
        "description": "Real-world cooling system failure analysis.",
        "section_keywords": ["case study", "failure", "repair", "diagnosis"],
    },
]


async def main():
    await init_db()
    logger.info("Database initialised.")

    async with AsyncSessionLocal() as session:
        # ------------------------------------------------------------------
        # Step 1: Ingest source document
        # ------------------------------------------------------------------
        logger.info("Step 1: Source Sentinel — ingesting technical manual...")
        sentinel = SourceSentinelAgent(session)
        sentinel_result = await sentinel.run({
            "title": "Heavy Truck Cooling Systems — Technical Reference Manual v2.1",
            "publisher": "CFRS Technical Institute",
            "file_path": str(MANUAL_PATH),
            "trust_tier": "tier2",
            "edition": "2.1",
            "publication_date": "2023-06-01",
            "license": "CC BY-NC 4.0",
            "metadata": {"academy": "cfrs_academy", "subject": "heavy_truck_cooling"},
        })
        source_id = sentinel_result["source_id"]
        logger.info("Source registered: %s (hash=%s)", source_id, sentinel_result["document_hash"])
        logger.info("Text blocks extracted: %d", sentinel_result["text_blocks_extracted"])

        await session.commit()

        # ------------------------------------------------------------------
        # Step 2: Extract claims and build knowledge graph
        # ------------------------------------------------------------------
        logger.info("Step 2: Knowledge Cartographer — extracting claims...")
        cartographer = KnowledgeCartographerAgent(session)
        cart_result = await cartographer.run({
            "source_id": source_id,
            "concept_domain": "heavy_truck_maintenance",
            "confidence_base": 0.70,
            "max_claims": 200,
        })
        logger.info(
            "Claims created: %d, Concepts: %d, Relationships: %d",
            cart_result["claims_created"],
            cart_result["concepts_created"],
            cart_result["relationships_created"],
        )

        await session.commit()

        # ------------------------------------------------------------------
        # Step 3: Add expert-curated relationships to knowledge graph
        # ------------------------------------------------------------------
        logger.info("Step 3: Adding expert-curated knowledge graph relationships...")
        graph = KnowledgeGraphManager(session)
        for parent, rel_type, child in EXPERT_RELATIONSHIPS:
            await graph.add_relationship(parent, rel_type, child)
        await session.commit()
        logger.info("Expert relationships added.")

        # ------------------------------------------------------------------
        # Step 4: Verify all draft claims (simulated human review)
        # ------------------------------------------------------------------
        logger.info("Step 4: Verifying draft claims (simulated human review)...")
        ledger = ClaimLedger(session)
        draft_claims = await ledger.list_claims(
            source_id=source_id,
            status=ClaimStatus.DRAFT,
            limit=500,
        )
        verified_count = 0
        for claim in draft_claims:
            await ledger.verify_claim(
                claim.claim_id,
                reviewer="cfrs_domain_expert",
                notes="Verified against CFRS Technical Institute curriculum standards.",
            )
            verified_count += 1
        await session.commit()
        logger.info("Verified %d claims.", verified_count)

        # ------------------------------------------------------------------
        # Step 5: Build curriculum
        # ------------------------------------------------------------------
        logger.info("Step 5: Curriculum Architect — building course...")
        architect = CurriculumArchitectAgent(session)

        # Get all verified claims for this source
        verified_claims = await ledger.list_claims(
            source_id=source_id,
            status=ClaimStatus.VERIFIED,
            limit=500,
        )
        claim_ids = [c.claim_id for c in verified_claims]

        arch_result = await architect.run({
            "course_title": "Heavy Truck Cooling Systems",
            "academy_node": "cfrs_academy",
            "description": (
                "A comprehensive vocational course on heavy truck cooling system "
                "operation, diagnosis, and repair. Suitable for Level 2 automotive "
                "technicians and fleet maintenance personnel."
            ),
            "learning_objectives": [
                "Describe the function and components of a heavy truck cooling system.",
                "Explain thermostat operation and diagnose thermostat failures.",
                "Perform fan clutch diagnostic tests.",
                "Analyse cooling system failure case studies.",
            ],
            "module_definitions": [
                {
                    "title": mod["title"],
                    "description": mod["description"],
                }
                for mod in MODULE_DEFS
            ],
            "version": "1.0",
        })
        logger.info(
            "Course built: %s | Modules: %d | Lessons: %d",
            arch_result["course_id"],
            arch_result["modules_created"],
            arch_result["lessons_created"],
        )

        await session.commit()

        # ------------------------------------------------------------------
        # Step 6: Initial integrity audit
        # ------------------------------------------------------------------
        logger.info("Step 6: Integrity Auditor — initial audit pass...")
        auditor = IntegrityAuditorAgent(session)
        audit_result = await auditor.run({"mode": "full"})
        logger.info("Audit result: %s", audit_result)

        await session.commit()

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        print("\n" + "="*70)
        print("CFRS ACADEMY — SEED COMPLETE")
        print("="*70)
        print(f"  Source ID:         {source_id}")
        print(f"  Claims verified:   {verified_count}")
        print(f"  Course ID:         {arch_result['course_id']}")
        print(f"  Modules created:   {arch_result['modules_created']}")
        print(f"  Lessons created:   {arch_result['lessons_created']}")
        print(f"  Audit report ID:   {audit_result.get('report_id', 'N/A')}")
        print("="*70)
        print("\nStart the API server: python main.py")
        print("Browse the API docs:  http://localhost:8000/docs\n")


if __name__ == "__main__":
    asyncio.run(main())
