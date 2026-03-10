"""
UAE v3 — Federation Transport Client

Sends signed federation messages to remote nodes over HTTP.

Every outgoing message:
  1. Is built with a message_id, timestamp, and nonce
  2. Is signed with this node's private key
  3. Is sent to the target node's federation endpoint
  4. Retried up to UAE_FEDERATION_MAX_RETRIES times on network failure
  5. Is logged in the FederatedClaimRecord with its signature

Message types (matching existing federation protocol):
  - PUBLISH_CLAIM
  - IMPORT_CLAIM
  - CONTEST_CLAIM
  - ADOPT_CLAIM
  - SYNC_REQUEST
  - ATTESTATION_SHARE
  - HANDSHAKE_HELLO
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx

from core.federation.message_signing import build_message, sign_message

logger = logging.getLogger(__name__)

_MAX_RETRIES = int(os.environ.get("UAE_FEDERATION_MAX_RETRIES", "3"))
_TIMEOUT_SECS = float(os.environ.get("UAE_FEDERATION_TIMEOUT_SECS", "10.0"))
_RETRY_BASE_SECS = float(os.environ.get("UAE_FEDERATION_RETRY_BASE_SECS", "1.0"))


class TransportError(Exception):
    """Raised when a federation transport operation fails unrecoverably."""


class FederationTransportClient:
    """
    HTTP client for inter-node federation messaging.

    Usage:
        client = FederationTransportClient(
            sender_node_id="node-a",
            private_key_pem=my_private_key,
            algorithm="RSA-SHA256",
        )
        response = await client.send_message(
            target_url="https://node-b.example.com",
            message_type="PUBLISH_CLAIM",
            body={"claim_id": "...", "snapshot": {...}},
            recipient_node_id="node-b",
        )
    """

    def __init__(
        self,
        sender_node_id: str,
        private_key_pem: str,
        algorithm: str = "RSA-SHA256",
        api_key: Optional[str] = None,
    ) -> None:
        self.sender_node_id = sender_node_id
        self._private_key_pem = private_key_pem
        self.algorithm = algorithm
        self._api_key = api_key

    async def send_message(
        self,
        target_url: str,
        message_type: str,
        body: dict[str, Any],
        *,
        recipient_node_id: Optional[str] = None,
        endpoint: str = "/api/v1/federation/transport/receive",
    ) -> dict:
        """
        Build, sign, and deliver a federation message.
        Retries on network failures with exponential backoff.
        Returns the response body dict.
        """
        message = build_message(
            message_type=message_type,
            sender_node_id=self.sender_node_id,
            body=body,
            recipient_node_id=recipient_node_id,
        )
        signed = sign_message(message, self._private_key_pem, self.algorithm)

        url = target_url.rstrip("/") + endpoint
        headers = {
            "Content-Type": "application/json",
            "X-UAE-Node-ID": self.sender_node_id,
        }
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT_SECS) as client:
                    response = await client.post(url, json=signed, headers=headers)

                if response.status_code == 200:
                    logger.info(
                        "Federation message %s sent to %s (type=%s, attempt=%d)",
                        signed["header"]["message_id"], target_url, message_type, attempt,
                    )
                    return response.json()
                elif response.status_code in (400, 401, 403, 422):
                    # Non-retryable errors
                    raise TransportError(
                        f"Federation endpoint rejected message: "
                        f"HTTP {response.status_code} — {response.text[:200]}"
                    )
                else:
                    last_exc = TransportError(
                        f"HTTP {response.status_code} from {url}"
                    )
                    logger.warning("Federation send failed (attempt %d): %s", attempt, last_exc)

            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("Federation network error (attempt %d): %s", attempt, exc)

            if attempt < _MAX_RETRIES:
                wait = _RETRY_BASE_SECS * (2 ** (attempt - 1))
                logger.debug("Retrying in %.1fs", wait)
                time.sleep(wait)

        raise TransportError(
            f"Federation message delivery failed after {_MAX_RETRIES} attempts: {last_exc}"
        )

    async def perform_handshake(
        self,
        target_url: str,
        hello_payload: dict,
    ) -> dict:
        """Send a HANDSHAKE_HELLO to a remote node."""
        return await self.send_message(
            target_url=target_url,
            message_type="HANDSHAKE_HELLO",
            body=hello_payload,
            endpoint="/api/v1/federation/transport/handshake",
        )

    async def fetch_remote_snapshot(
        self,
        target_url: str,
        claim_ids: list[str],
    ) -> dict:
        """Request claim snapshots from a remote node."""
        return await self.send_message(
            target_url=target_url,
            message_type="SYNC_REQUEST",
            body={"claim_ids": claim_ids},
        )
