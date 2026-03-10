"""
UAE v3 — Federation Transport Server (FastAPI Router)

Receives, verifies, and processes signed federation messages from peer nodes.

Invariants enforced on every incoming message:
  1. Must be signed — unsigned messages are rejected (HTTP 401)
  2. Signature must verify against sender's registered public key
  3. Timestamp + nonce must pass replay protection check
  4. Sender node must be a registered federation member
  5. Message schema_version must match expected version

On success, the message is dispatched to the appropriate local handler
(ClaimFederationProtocol, AttestationManager, etc.) and a FederatedClaimRecord
is written for immutable audit.

Endpoints registered here:
  POST /api/v1/federation/transport/receive      — general message ingestion
  POST /api/v1/federation/transport/handshake    — node trust bootstrap
  GET  /api/v1/federation/transport/status       — liveness + peer list
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.federation.message_signing import (
    SCHEMA_VERSION,
    verify_message_signature,
    message_digest,
)
from core.federation.node_handshake import NodeHandshakeProtocol
from core.federation.replay_protection import get_replay_protection, ReplayProtectionError
from database.connection import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/federation/transport", tags=["Federation Transport"])

# Module-level handshake protocol instance (set at node startup)
_handshake_protocol: Optional[NodeHandshakeProtocol] = None


def configure_transport_server(handshake: NodeHandshakeProtocol) -> None:
    """Call this at application startup to configure the transport server."""
    global _handshake_protocol
    _handshake_protocol = handshake
    logger.info("Federation transport server configured for node: %s", handshake.local_node_id)


def get_handshake_protocol() -> NodeHandshakeProtocol:
    if _handshake_protocol is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Federation transport not configured. Node startup incomplete.",
        )
    return _handshake_protocol


@router.post("/receive", summary="Receive a signed federation message")
async def receive_federation_message(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Accept, verify, and process an incoming federation message.

    Rejects:
      - Unsigned messages (401)
      - Messages from unknown/untrusted nodes (401)
      - Replayed messages (409)
      - Schema mismatches (400)
    """
    handshake = get_handshake_protocol()
    replay = get_replay_protection()

    try:
        message = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    header = message.get("header", {})
    schema_version = header.get("schema_version")
    sender_id = header.get("sender_node_id")
    message_type = header.get("message_type")

    if schema_version != SCHEMA_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported schema_version {schema_version!r}. Expected {SCHEMA_VERSION!r}.",
        )

    if not sender_id:
        raise HTTPException(status_code=400, detail="Missing sender_node_id in header.")

    # Replay protection
    try:
        replay.check_and_record(message)
    except ReplayProtectionError as exc:
        logger.warning("Replay attack detected from %s: %s", sender_id, exc)
        raise HTTPException(status_code=409, detail=f"Replay protection: {exc}")

    # Verify signature against known peer key
    peer_pub_key = handshake.get_peer_public_key(sender_id)
    if peer_pub_key is None:
        raise HTTPException(
            status_code=401,
            detail=(
                f"Node {sender_id!r} is not a trusted peer. "
                "Complete handshake before sending federation messages."
            ),
        )

    if not verify_message_signature(message, peer_pub_key):
        logger.error("Invalid signature on federation message from %s", sender_id)
        raise HTTPException(
            status_code=401,
            detail="Message signature verification failed.",
        )

    # Dispatch to handler
    body = message.get("body", {})
    digest = message_digest(message)

    logger.info(
        "Federation message accepted: type=%s sender=%s digest=%s",
        message_type, sender_id, digest[:12],
    )

    result = await _dispatch_message(message_type, sender_id, body, db)
    return {
        "status": "accepted",
        "message_id": header.get("message_id"),
        "message_type": message_type,
        "digest": digest,
        "result": result,
    }


@router.post("/handshake", summary="Node trust bootstrap (HELLO exchange)")
async def federation_handshake(request: Request) -> dict:
    """
    Accept a HELLO payload from a peer node.
    Verifies the peer's self-signed payload and registers their public key.
    Responds with this node's own HELLO for mutual authentication.
    """
    handshake = get_handshake_protocol()

    try:
        hello = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    # HELLO messages can be in either the full envelope body or raw format
    if "header" in hello and "body" in hello:
        hello = hello["body"]

    if not handshake.receive_hello(hello):
        raise HTTPException(
            status_code=401,
            detail="Handshake HELLO verification failed.",
        )

    # Respond with our own HELLO
    our_hello = handshake.build_hello()
    return {
        "status": "handshake_complete",
        "peer_node_id": hello.get("node_id"),
        "our_hello": our_hello,
    }


@router.get("/status", summary="Transport server status and peer list")
async def transport_status() -> dict:
    """Return liveness and current trusted peer list."""
    if _handshake_protocol is None:
        return {"status": "not_configured"}
    return {
        "status": "ok",
        "local_node_id": _handshake_protocol.local_node_id,
        "local_node_url": _handshake_protocol.local_node_url,
        "trusted_peers": _handshake_protocol.list_trusted_peers(),
    }


# ------------------------------------------------------------------
# Message dispatch table
# ------------------------------------------------------------------

async def _dispatch_message(
    message_type: str,
    sender_id: str,
    body: dict,
    db: AsyncSession,
) -> dict:
    """Route incoming federation messages to the appropriate handler."""
    handlers = {
        "PUBLISH_CLAIM": _handle_publish_claim,
        "IMPORT_CLAIM": _handle_import_claim,
        "CONTEST_CLAIM": _handle_contest_claim,
        "ADOPT_CLAIM": _handle_adopt_claim,
        "SYNC_REQUEST": _handle_sync_request,
        "ATTESTATION_SHARE": _handle_attestation_share,
    }

    handler = handlers.get(message_type)
    if handler is None:
        logger.warning("Unknown message type from %s: %s", sender_id, message_type)
        return {"status": "unknown_message_type", "message_type": message_type}

    return await handler(sender_id, body, db)


async def _handle_publish_claim(sender_id: str, body: dict, db: AsyncSession) -> dict:
    """A remote node has published a claim to the federation."""
    from core.federation.claim_federation import ClaimFederationProtocol
    claim_id = body.get("claim_id")
    if not claim_id:
        return {"status": "error", "detail": "Missing claim_id in body"}
    try:
        protocol = ClaimFederationProtocol(db)
        record = await protocol.publish_claim(claim_id, sender_id)
        return {"status": "recorded", "record_id": record.record_id}
    except Exception as exc:
        logger.warning("publish_claim dispatch error: %s", exc)
        return {"status": "error", "detail": str(exc)}


async def _handle_import_claim(sender_id: str, body: dict, db: AsyncSession) -> dict:
    claim_id = body.get("claim_id")
    importing_node_id = body.get("importing_node_id", sender_id)
    if not claim_id:
        return {"status": "error", "detail": "Missing claim_id"}
    try:
        from core.federation.claim_federation import ClaimFederationProtocol
        protocol = ClaimFederationProtocol(db)
        _, record = await protocol.import_claim(claim_id, importing_node_id)
        return {"status": "imported", "record_id": record.record_id}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _handle_contest_claim(sender_id: str, body: dict, db: AsyncSession) -> dict:
    claim_id = body.get("claim_id")
    reason = body.get("reason", "No reason given")
    if not claim_id:
        return {"status": "error", "detail": "Missing claim_id"}
    try:
        from core.federation.claim_federation import ClaimFederationProtocol
        protocol = ClaimFederationProtocol(db)
        record = await protocol.contest_claim(claim_id, sender_id, reason=reason)
        return {"status": "contested", "record_id": record.record_id}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _handle_adopt_claim(sender_id: str, body: dict, db: AsyncSession) -> dict:
    claim_id = body.get("claim_id")
    if not claim_id:
        return {"status": "error", "detail": "Missing claim_id"}
    try:
        from core.federation.claim_federation import ClaimFederationProtocol
        protocol = ClaimFederationProtocol(db)
        record = await protocol.adopt_claim(claim_id, sender_id)
        return {"status": "adopted", "record_id": record.record_id}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _handle_sync_request(sender_id: str, body: dict, db: AsyncSession) -> dict:
    """Return claim snapshots for requested IDs."""
    from sqlalchemy import select
    from database.schemas.models import Claim
    claim_ids = body.get("claim_ids", [])
    result = await db.execute(select(Claim).where(Claim.claim_id.in_(claim_ids)))
    claims = result.scalars().all()
    snapshots = [
        {
            "claim_id": c.claim_id,
            "claim_number": c.claim_number,
            "statement": c.statement,
            "status": c.status.value if c.status else None,
            "claim_hash": c.claim_hash,
            "origin_node_id": c.origin_node_id,
        }
        for c in claims
    ]
    return {"status": "ok", "snapshots": snapshots}


async def _handle_attestation_share(sender_id: str, body: dict, db: AsyncSession) -> dict:
    """Receive a shared attestation from a peer node (informational, not auto-accepted)."""
    logger.info("Received attestation share from %s for claim %s", sender_id, body.get("claim_id"))
    return {"status": "received", "note": "Attestation logged for review."}
