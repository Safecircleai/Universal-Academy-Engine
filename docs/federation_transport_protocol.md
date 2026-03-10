# UAE v3 — Federation Transport Protocol

## Overview

UAE v3 introduces a real HTTP transport layer for inter-node federation.
Nodes communicate by sending signed JSON message envelopes over HTTPS.

## Message Envelope

```json
{
  "header": {
    "message_id":       "<uuid4>",
    "message_type":     "PUBLISH_CLAIM",
    "sender_node_id":   "node-a",
    "recipient_node_id": "node-b",
    "timestamp":        "2026-03-10T00:00:00+00:00",
    "nonce":            "<32-hex-chars>",
    "schema_version":   "uae-federation-v3"
  },
  "body": { ... },
  "signature": "<base64-RSA-SHA256>"
}
```

The signature covers the canonical JSON of `header + body` (not the signature field itself).

## Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `HANDSHAKE_HELLO` | bidirectional | Trust bootstrap — node introduces itself |
| `PUBLISH_CLAIM` | A → B | Notify peer that a claim has been published |
| `IMPORT_CLAIM` | B → A | Node B imports a published claim |
| `CONTEST_CLAIM` | B → A | Node B disputes an imported claim |
| `ADOPT_CLAIM` | A → B | Node A accepts claim after contest resolution |
| `SYNC_REQUEST` | bidirectional | Request claim snapshots by ID |
| `ATTESTATION_SHARE` | bidirectional | Share an attestation with a peer (informational) |

## Endpoints

```
POST /api/v1/federation/transport/receive      — receive general messages
POST /api/v1/federation/transport/handshake   — node trust bootstrap
GET  /api/v1/federation/transport/status      — node status + peer list
```

## Handshake Protocol

Before nodes can exchange federation messages, they must complete a mutual handshake:

1. **Node A → Node B**: `POST /api/v1/federation/transport/handshake` with Node A's HELLO payload
2. **Node B verifies** Node A's signature against the embedded public key
3. **Node B responds** with its own HELLO (mutual authentication)
4. Both nodes now trust each other for message verification

HELLO payload:
```json
{
  "schema_version": "uae-handshake-v1",
  "node_id": "node-a",
  "public_key_pem": "-----BEGIN PUBLIC KEY-----\n...",
  "node_url": "https://node-a.example.com",
  "nonce": "<32-hex>",
  "timestamp": "<ISO-8601>",
  "algorithm": "RSA-SHA256",
  "signature": "<base64>"
}
```

## Security Guarantees

1. **Authentication**: Every message is signed; only trusted nodes (post-handshake) are accepted
2. **Integrity**: Signature covers header + body; tampering is detected
3. **Replay Protection**: `message_id` + `timestamp` are checked against a 5-minute window
4. **No silent failures**: Invalid signatures return HTTP 401; replays return HTTP 409

## Replay Protection

- Window: 300 seconds (configurable via `UAE_FEDERATION_REPLAY_WINDOW_SECS`)
- `message_id` is stored until it ages out of the window
- Cache size limit: 10,000 entries (LRU eviction)
- **Production note**: Use Redis-backed store for multi-process deployments

## Failure Recovery

The `SyncQueue` provides at-least-once delivery:
- Failed messages are queued and retried with exponential backoff
- Max retries configurable via `UAE_FEDERATION_MAX_RETRIES`
- Failed messages after max retries are logged for manual intervention

## Sovereignty Guarantee

Each node remains independently authoritative. The transport layer delivers messages
but does not force automatic state changes. Imported claims require explicit adoption.
Nodes may reject imports or contest claims per their governance policy.
