"""
UAE v3 — Replay Attack Protection

Prevents replay attacks on federation messages by:
  1. Tracking seen message IDs (nonce deduplication)
  2. Rejecting messages with timestamps outside the acceptance window
  3. Enforcing monotonic message ordering per sender (optional)

Config:
  UAE_FEDERATION_REPLAY_WINDOW_SECS — default 300 (5 minutes)
  Messages older than this window are rejected.

In production, the seen-nonce store should be backed by Redis or PostgreSQL
for multi-process deployments. This implementation is in-memory per process.
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_REPLAY_WINDOW_SECS = int(os.environ.get("UAE_FEDERATION_REPLAY_WINDOW_SECS", "300"))
# Max cached nonces (LRU eviction)
_MAX_NONCE_CACHE = int(os.environ.get("UAE_FEDERATION_NONCE_CACHE_SIZE", "10000"))


class ReplayProtectionError(Exception):
    """Raised when a federation message is rejected as a replay."""


class ReplayProtection:
    """
    In-memory replay protection for federation messages.

    Thread-safety: The OrderedDict operations are GIL-protected in CPython,
    but for true multi-worker deployments use the Redis-backed variant.
    """

    def __init__(
        self,
        window_secs: int = _REPLAY_WINDOW_SECS,
        max_cache: int = _MAX_NONCE_CACHE,
    ) -> None:
        self.window_secs = window_secs
        self.max_cache = max_cache
        # message_id -> seen_at (unix timestamp)
        self._seen: OrderedDict[str, float] = OrderedDict()

    def check_and_record(self, message: dict) -> None:
        """
        Check message for replay and record it if accepted.
        Raises ReplayProtectionError if:
          - message_id was seen before
          - timestamp is outside the acceptance window
        """
        header = message.get("header", {})
        message_id = header.get("message_id")
        timestamp_str = header.get("timestamp")

        if not message_id:
            raise ReplayProtectionError("Message missing message_id in header.")
        if not timestamp_str:
            raise ReplayProtectionError("Message missing timestamp in header.")

        # Check timestamp window
        self._check_timestamp(timestamp_str)

        # Check nonce deduplication
        if message_id in self._seen:
            raise ReplayProtectionError(
                f"Duplicate message_id detected (replay attack?): {message_id!r}"
            )

        # Record
        self._evict_expired()
        self._seen[message_id] = time.monotonic()

        # Enforce max cache size (LRU eviction)
        while len(self._seen) > self.max_cache:
            self._seen.popitem(last=False)

        logger.debug("Replay check passed: message_id=%s", message_id)

    def _check_timestamp(self, timestamp_str: str) -> None:
        """Reject messages outside the time window."""
        try:
            msg_time = datetime.fromisoformat(timestamp_str)
            if msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=timezone.utc)
        except ValueError:
            raise ReplayProtectionError(f"Invalid timestamp format: {timestamp_str!r}")

        now = datetime.now(timezone.utc)
        delta = abs((now - msg_time).total_seconds())
        if delta > self.window_secs:
            raise ReplayProtectionError(
                f"Message timestamp {timestamp_str!r} is {delta:.0f}s outside "
                f"the {self.window_secs}s acceptance window."
            )

    def _evict_expired(self) -> None:
        """Remove nonces older than the window (monotonic clock)."""
        cutoff = time.monotonic() - self.window_secs
        while self._seen:
            oldest_id, oldest_ts = next(iter(self._seen.items()))
            if oldest_ts < cutoff:
                del self._seen[oldest_id]
            else:
                break

    def seen_count(self) -> int:
        return len(self._seen)


# Module-level singleton
_replay_protection: Optional[ReplayProtection] = None


def get_replay_protection() -> ReplayProtection:
    global _replay_protection
    if _replay_protection is None:
        _replay_protection = ReplayProtection()
    return _replay_protection
