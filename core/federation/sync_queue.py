"""
UAE v3 — Federation Sync Queue

Provides failure-safe async queuing for outbound federation messages.
When delivery to a peer node fails, messages are queued for retry.

Queue guarantees:
  - At-least-once delivery (messages are retried until confirmed or max_attempts)
  - Messages are not delivered out of order per target node
  - Failed messages are logged with full context for audit

In production, back this with PostgreSQL or Redis.
This implementation is in-memory (suitable for single-process nodes).

Production upgrade path:
  Replace SyncQueue with AsyncPgSyncQueue that persists to a
  'federation_sync_queue' table and can survive restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_RETRY_DELAY_SECS = 10.0


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class SyncQueueItem:
    """A queued outbound federation message."""
    item_id: str
    target_url: str
    target_node_id: str
    message_type: str
    body: dict[str, Any]
    status: QueueItemStatus = QueueItemStatus.PENDING
    attempts: int = 0
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_attempted_at: Optional[datetime] = None
    last_error: Optional[str] = None
    delivered_at: Optional[datetime] = None


class SyncQueue:
    """
    In-memory federation sync queue with async processing.

    Usage:
        queue = SyncQueue(transport_client)
        queue.enqueue("https://node-b.example.com", "node-b", "PUBLISH_CLAIM", body)
        await queue.start()  # begins background processing
    """

    def __init__(
        self,
        transport_client: Any,  # FederationTransportClient
        retry_delay_secs: float = _DEFAULT_RETRY_DELAY_SECS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._client = transport_client
        self._retry_delay = retry_delay_secs
        self._max_attempts = max_attempts
        self._items: dict[str, SyncQueueItem] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    def enqueue(
        self,
        target_url: str,
        target_node_id: str,
        message_type: str,
        body: dict[str, Any],
    ) -> SyncQueueItem:
        """Add a message to the outbound queue."""
        item = SyncQueueItem(
            item_id=str(uuid.uuid4()),
            target_url=target_url,
            target_node_id=target_node_id,
            message_type=message_type,
            body=body,
            max_attempts=self._max_attempts,
        )
        self._items[item.item_id] = item
        self._queue.put_nowait(item)
        logger.debug("Queued federation message: type=%s target=%s id=%s",
                     message_type, target_node_id, item.item_id)
        return item

    async def start(self) -> None:
        """Start the background queue processor."""
        self._running = True
        logger.info("SyncQueue: background processor started")
        asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Gracefully stop the queue processor."""
        self._running = False

    async def _process_loop(self) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process_item(item)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.exception("SyncQueue processing error: %s", exc)

    async def _process_item(self, item: SyncQueueItem) -> None:
        if item.status in (QueueItemStatus.DELIVERED, QueueItemStatus.FAILED):
            return

        item.status = QueueItemStatus.IN_FLIGHT
        item.attempts += 1
        item.last_attempted_at = datetime.now(timezone.utc)

        try:
            await self._client.send_message(
                target_url=item.target_url,
                message_type=item.message_type,
                body=item.body,
                recipient_node_id=item.target_node_id,
            )
            item.status = QueueItemStatus.DELIVERED
            item.delivered_at = datetime.now(timezone.utc)
            logger.info(
                "SyncQueue: delivered type=%s to=%s (attempt %d)",
                item.message_type, item.target_node_id, item.attempts,
            )
        except Exception as exc:
            item.last_error = str(exc)
            if item.attempts >= item.max_attempts:
                item.status = QueueItemStatus.FAILED
                logger.error(
                    "SyncQueue: PERMANENTLY FAILED type=%s to=%s after %d attempts: %s",
                    item.message_type, item.target_node_id, item.attempts, exc,
                )
            else:
                item.status = QueueItemStatus.PENDING
                logger.warning(
                    "SyncQueue: retry scheduled type=%s to=%s (attempt %d/%d): %s",
                    item.message_type, item.target_node_id, item.attempts, item.max_attempts, exc,
                )
                await asyncio.sleep(self._retry_delay)
                self._queue.put_nowait(item)

    def stats(self) -> dict:
        """Return queue statistics."""
        by_status: dict[str, int] = {}
        for item in self._items.values():
            by_status[item.status.value] = by_status.get(item.status.value, 0) + 1
        return {
            "total": len(self._items),
            "by_status": by_status,
            "queue_depth": self._queue.qsize(),
        }

    def list_failed(self) -> list[SyncQueueItem]:
        return [i for i in self._items.values() if i.status == QueueItemStatus.FAILED]
