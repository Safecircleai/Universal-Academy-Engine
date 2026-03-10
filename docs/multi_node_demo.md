# UAE v3 — Multi-Node Federation Demo

## What This Demo Proves

- Two independent UAE nodes (A and B) can exchange signed federation messages
- Node A publishes a verified claim; Node B imports it
- Node B can contest the claim; Node A can respond and adopt
- Credentials are only issued from published, approved curriculum
- Every action is logged in the immutable federation event audit trail

## Quick Run (Docker Compose)

```bash
# Start both nodes + PostgreSQL
docker-compose -f docker-compose.multi-node.yml up -d

# Wait for nodes to be healthy (about 30 seconds)
# Then run the demo script:
python demo/run_demo.py
```

## Manual Step-by-Step

### Step 1: Start Node A and Node B

```bash
# Terminal 1: Node A (port 8001)
DATABASE_URL="sqlite+aiosqlite:///./node_a.db" \
UAE_NODE_ID="node-a" \
UAE_AUTH_ENABLED="false" \
uvicorn main:app --port 8001

# Terminal 2: Node B (port 8002)
DATABASE_URL="sqlite+aiosqlite:///./node_b.db" \
UAE_NODE_ID="node-b" \
UAE_AUTH_ENABLED="false" \
uvicorn main:app --port 8002
```

### Step 2: Node A Creates a Verified Claim

```bash
# Register a source on Node A
curl -s -X POST http://localhost:8001/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo Source","publisher":"Demo Authority","trust_tier":"TIER1","document_hash":"sha256:'$(python3 -c "import secrets; print(secrets.token_hex(32))")'"}' \
  | python3 -m json.tool

# Create and verify a claim (use source_id from above)
SOURCE_ID="<source_id_from_above>"
curl -s -X POST http://localhost:8001/api/v1/claims \
  -H "Content-Type: application/json" \
  -d '{"statement":"Electrical circuits require a complete conductive path.","source_id":"'$SOURCE_ID'","confidence_score":0.92}' \
  | python3 -m json.tool
```

### Step 3: Node A Publishes the Claim

```bash
CLAIM_ID="<claim_id>"
NODE_A_ID="<node_id>"
curl -s -X POST http://localhost:8001/api/v1/federation/claims/$CLAIM_ID/publish \
  -H "Content-Type: application/json" \
  -d '{"publishing_node_id":"'$NODE_A_ID'"}' \
  | python3 -m json.tool
```

### Step 4: Node B Imports the Claim

```bash
NODE_B_ID="<node_b_node_id>"
curl -s -X POST http://localhost:8002/api/v1/federation/claims/$CLAIM_ID/import \
  -H "Content-Type: application/json" \
  -d '{"importing_node_id":"'$NODE_B_ID'"}' \
  | python3 -m json.tool
```

### Step 5: Node B Contests

```bash
curl -s -X POST http://localhost:8002/api/v1/federation/claims/$CLAIM_ID/contest \
  -H "Content-Type: application/json" \
  -d '{"contesting_node_id":"'$NODE_B_ID'","reason":"Lacks AC/DC circuit specificity."}' \
  | python3 -m json.tool
```

### Step 6: Node A Adopts After Resolution

```bash
curl -s -X POST http://localhost:8001/api/v1/federation/claims/$CLAIM_ID/adopt \
  -H "Content-Type: application/json" \
  -d '{"adopting_node_id":"'$NODE_A_ID'","resolution_notes":"Reviewed — claim is accurate for general circuits."}' \
  | python3 -m json.tool
```

### Step 7: Inspect Audit Trail

```bash
# Node A audit log
curl -s http://localhost:8001/api/v1/federation/claims/$CLAIM_ID/events | python3 -m json.tool

# Generate full audit report
curl -s -X POST http://localhost:8001/api/v1/audit/run \
  -H "Content-Type: application/json" \
  -d '{"report_type":"claim","subject_id":"'$CLAIM_ID'","generated_by":"demo"}' \
  | python3 -m json.tool
```

## What to Check

| Invariant | Where to verify |
|-----------|----------------|
| Claim published only when VERIFIED | Try publishing a DRAFT claim — should get 422 |
| Credential only from published course | Try issuing from DRAFT course — should fail |
| All federation events logged | GET /api/v1/federation/claims/{id}/events |
| Contested claims marked CONTESTED | GET /api/v1/claims/{id} — check claim_category |
| Audit trail complete | POST /api/v1/audit/run |

## Transport Layer Demo (Signed Messages)

The transport layer tests verify signed message exchange:

```bash
pytest tests/test_federation_transport.py -v
pytest tests/test_multi_node.py -v
```

These tests run without network — they use in-memory sessions and test
the full signing → verification → replay-protection → dispatch chain.
