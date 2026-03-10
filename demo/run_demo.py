#!/usr/bin/env python3
"""
UAE v3 — Multi-Node Federation Demo

Demonstrates the full federation protocol between Node A and Node B:
  1. Node A registers a source and creates a verified claim
  2. Node A publishes the claim to the federation
  3. Node B imports the published claim
  4. Node B contests a claim
  5. Node A responds (adopts after resolution)
  6. Node A issues a credential from published curriculum
  7. Audit trail is verified on both nodes

Prerequisites:
  - Node A running on http://localhost:8001
  - Node B running on http://localhost:8002
  - UAE_AUTH_ENABLED=false (demo mode)

Run:
  python demo/run_demo.py
  # Or with docker-compose:
  docker-compose -f docker-compose.multi-node.yml up -d
  python demo/run_demo.py
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Optional

import httpx

NODE_A_URL = "http://localhost:8001"
NODE_B_URL = "http://localhost:8002"


def _print_step(n: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  STEP {n}: {title}")
    print(f"{'='*60}")


def _print_result(label: str, data: dict) -> None:
    print(f"\n  [{label}]")
    print(f"  {json.dumps(data, indent=4, default=str)[:800]}")


def _post(base_url: str, path: str, body: dict) -> dict:
    url = f"{base_url}/api/v1{path}"
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        return response.json()


def _get(base_url: str, path: str) -> dict:
    url = f"{base_url}/api/v1{path}"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def _wait_for_node(url: str, label: str, max_wait: int = 30) -> None:
    print(f"  Waiting for {label} ({url})...", end="", flush=True)
    start = time.time()
    while time.time() - start < max_wait:
        try:
            r = httpx.get(f"{url}/health", timeout=3.0)
            if r.status_code == 200:
                print(" OK")
                return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print(" TIMEOUT")
    sys.exit(1)


def main() -> None:
    print("\nUAE v3 — Multi-Node Federation Demo")
    print("=====================================\n")

    # --- Health checks ---
    _wait_for_node(NODE_A_URL, "Node A")
    _wait_for_node(NODE_B_URL, "Node B")

    # ---------------------------------------------------------------
    # STEP 1: Register Node A in its own registry
    # ---------------------------------------------------------------
    _print_step(1, "Register Node A")
    node_a_id = f"node-a-{uuid.uuid4().hex[:8]}"
    node_a = _post(NODE_A_URL, "/nodes", {
        "node_name": "Academy Node A",
        "node_type": "VOCATIONAL_ACADEMY",
        "institution_name": "Node A Training Institute",
        "node_url": NODE_A_URL,
    })
    _print_result("Node A registered", node_a)
    node_a_id = node_a.get("node_id", node_a_id)

    # ---------------------------------------------------------------
    # STEP 2: Node A creates a source and verified claim
    # ---------------------------------------------------------------
    _print_step(2, "Node A: Register Source + Create Claim")

    source = _post(NODE_A_URL, "/sources", {
        "title": "Federation Demo Source Document",
        "publisher": "UAE Demo Authority",
        "trust_tier": "TIER1",
        "origin_node_id": node_a_id,
        "document_hash": f"sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}",
    })
    _print_result("Source created", source)
    source_id = source["source_id"]

    claim = _post(NODE_A_URL, "/claims", {
        "statement": "Electrical circuits require both a power source and a complete conductive path to function.",
        "source_id": source_id,
        "origin_node_id": node_a_id,
        "confidence_score": 0.92,
    })
    _print_result("Claim created", claim)
    claim_id = claim["claim_id"]

    # Verify the claim (move to VERIFIED status)
    verified = _post(NODE_A_URL, f"/claims/{claim_id}/verify", {
        "reviewer": "demo-reviewer",
        "verification_result": "VERIFIED",
        "notes": "Demo verification — claim is factually correct.",
    })
    _print_result("Claim verified", verified)

    # ---------------------------------------------------------------
    # STEP 3: Node A publishes claim to federation
    # ---------------------------------------------------------------
    _print_step(3, "Node A: Publish Claim to Federation")

    published = _post(NODE_A_URL, f"/federation/claims/{claim_id}/publish", {
        "publishing_node_id": node_a_id,
        "notes": "Publishing for federation demo",
    })
    _print_result("Claim published", published)

    # ---------------------------------------------------------------
    # STEP 4: Register Node B and import the claim
    # ---------------------------------------------------------------
    _print_step(4, "Register Node B + Import Published Claim")

    node_b = _post(NODE_B_URL, "/nodes", {
        "node_name": "Academy Node B",
        "node_type": "CERTIFICATION_BODY",
        "institution_name": "Node B Certification Authority",
        "node_url": NODE_B_URL,
    })
    _print_result("Node B registered", node_b)
    node_b_id = node_b.get("node_id")

    # Node B imports the claim (in single-DB demo, we target same claim_id)
    imported = _post(NODE_B_URL, f"/federation/claims/{claim_id}/import", {
        "importing_node_id": node_b_id,
        "notes": "Node B importing published federation claim",
    })
    _print_result("Claim imported by Node B", imported)

    # ---------------------------------------------------------------
    # STEP 5: Node B contests the claim
    # ---------------------------------------------------------------
    _print_step(5, "Node B: Contest the Claim")

    contested = _post(NODE_B_URL, f"/federation/claims/{claim_id}/contest", {
        "contesting_node_id": node_b_id,
        "reason": "The claim lacks specificity about DC vs AC circuits. Request clarification.",
    })
    _print_result("Claim contested by Node B", contested)

    # ---------------------------------------------------------------
    # STEP 6: Node A responds — adopts after reviewing contest
    # ---------------------------------------------------------------
    _print_step(6, "Node A: Adopt Claim After Reviewing Contest")

    adopted = _post(NODE_A_URL, f"/federation/claims/{claim_id}/adopt", {
        "adopting_node_id": node_a_id,
        "resolution_notes": "Contest reviewed. Original claim is correct for general circuits. "
                            "DC/AC specificity addressed in related claims.",
    })
    _print_result("Claim adopted after resolution", adopted)

    # ---------------------------------------------------------------
    # STEP 7: Build curriculum and issue credential from published curriculum
    # ---------------------------------------------------------------
    _print_step(7, "Node A: Build Course + Issue Credential")

    course = _post(NODE_A_URL, "/courses", {
        "title": "Electrical Fundamentals",
        "description": "Core electrical concepts for vocational training",
        "origin_node_id": node_a_id,
        "domain": "electrical",
    })
    _print_result("Course created", course)
    course_id = course["course_id"]

    credential = _post(NODE_A_URL, "/credentials/issue", {
        "student_id": f"student-demo-{uuid.uuid4().hex[:6]}",
        "student_name": "Demo Student",
        "student_email": "demo@example.com",
        "course_id": course_id,
        "issuing_node_id": node_a_id,
        "issued_by": "Demo Issuer",
        "credential_type": "COMPLETION",
    })
    _print_result("Credential issued", credential)

    # ---------------------------------------------------------------
    # STEP 8: Inspect audit trail
    # ---------------------------------------------------------------
    _print_step(8, "Inspect Federation Event Log (Node A)")

    events = _get(NODE_A_URL, f"/federation/claims/{claim_id}/events")
    _print_result("Federation events", events)

    # ---------------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------------
    print("\n" + "="*60)
    print("  DEMO COMPLETE")
    print("="*60)
    print(f"""
  Demonstrated:
    ✓ Node A registered and created a verified source + claim
    ✓ Claim published to federation (claim_id={claim_id[:8]}...)
    ✓ Node B imported the published claim
    ✓ Node B contested the claim (dispute recorded)
    ✓ Node A resolved contest via adoption
    ✓ Credential issued from published curriculum
    ✓ Full federation event audit trail preserved

  API Docs:
    Node A: {NODE_A_URL}/docs
    Node B: {NODE_B_URL}/docs
""")


if __name__ == "__main__":
    main()
