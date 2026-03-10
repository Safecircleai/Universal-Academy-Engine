"""
UAE v3 — LLM Client Adapter

Pluggable LLM adapter for UAE agents.
Agents MUST use this client — never call LLM APIs directly.

All calls are logged with:
  - model_id
  - prompt_type
  - input token estimate
  - output hash (for audit)
  - latency

Currently supported backends:
  - "anthropic" (Claude API via anthropic SDK)
  - "openai" (OpenAI-compatible API)
  - "stub" (deterministic stub for testing — NO network calls)

Configure via environment:
  UAE_LLM_BACKEND       — "anthropic" | "openai" | "stub" (default: "stub")
  UAE_LLM_MODEL_ID      — model identifier (e.g., "claude-sonnet-4-6")
  UAE_LLM_API_KEY       — API key (or use ANTHROPIC_API_KEY / OPENAI_API_KEY)
  UAE_LLM_MAX_TOKENS    — max output tokens (default: 2048)

IMPORTANT: Agents receive structured outputs only. Raw LLM text is NEVER
written directly to claims or curriculum without validation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BACKEND = os.environ.get("UAE_LLM_BACKEND", "stub")
_MODEL_ID = os.environ.get("UAE_LLM_MODEL_ID", "claude-sonnet-4-6")
_MAX_TOKENS = int(os.environ.get("UAE_LLM_MAX_TOKENS", "2048"))


class LLMError(Exception):
    """Raised when an LLM call fails."""


class LLMResponse:
    """Structured LLM response with audit metadata."""

    def __init__(
        self,
        content: str,
        model_id: str,
        prompt_type: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> None:
        self.content = content
        self.model_id = model_id
        self.prompt_type = prompt_type
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
        self.output_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def to_audit_record(self) -> dict:
        return {
            "model_id": self.model_id,
            "prompt_type": self.prompt_type,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "output_hash": self.output_hash,
        }


class LLMClient:
    """
    Pluggable LLM client adapter.

    Agents call complete() with a prompt_type (for audit logging) and
    a list of messages. The client returns a structured LLMResponse.
    """

    def __init__(
        self,
        backend: str = _BACKEND,
        model_id: str = _MODEL_ID,
        max_tokens: int = _MAX_TOKENS,
        api_key: Optional[str] = None,
    ) -> None:
        self.backend = backend
        self.model_id = model_id
        self.max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("UAE_LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        prompt_type: str = "generic",
        system: Optional[str] = None,
    ) -> LLMResponse:
        """
        Send messages to the LLM and return a structured response.

        messages format: [{"role": "user", "content": "..."}, ...]
        """
        start = time.monotonic()

        if self.backend == "stub":
            response = self._stub_complete(messages, prompt_type)
        elif self.backend == "anthropic":
            response = await self._anthropic_complete(messages, prompt_type, system)
        elif self.backend == "openai":
            response = await self._openai_complete(messages, prompt_type, system)
        else:
            raise LLMError(f"Unknown LLM backend: {self.backend!r}")

        latency_ms = int((time.monotonic() - start) * 1000)
        response.latency_ms = latency_ms
        logger.info(
            "LLM call: backend=%s model=%s type=%s tokens_in=%d tokens_out=%d latency=%dms hash=%s",
            self.backend, self.model_id, prompt_type,
            response.input_tokens, response.output_tokens,
            latency_ms, response.output_hash[:12],
        )
        return response

    def _stub_complete(self, messages: list[dict], prompt_type: str) -> LLMResponse:
        """Deterministic stub — returns structured placeholder JSON."""
        user_content = messages[-1]["content"] if messages else ""
        stub_output = json.dumps({
            "stub": True,
            "prompt_type": prompt_type,
            "input_preview": user_content[:100],
            "note": "LLM stub active. Set UAE_LLM_BACKEND=anthropic for real model calls.",
        })
        return LLMResponse(
            content=stub_output,
            model_id="stub",
            prompt_type=prompt_type,
            input_tokens=len(user_content.split()),
            output_tokens=20,
            latency_ms=0,
        )

    async def _anthropic_complete(
        self,
        messages: list[dict],
        prompt_type: str,
        system: Optional[str],
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError:
            raise LLMError("anthropic SDK not installed. Run: pip install anthropic")

        if not self._api_key:
            raise LLMError("No API key for Anthropic. Set ANTHROPIC_API_KEY.")

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = await client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            model_id=self.model_id,
            prompt_type=prompt_type,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=0,
        )

    async def _openai_complete(
        self,
        messages: list[dict],
        prompt_type: str,
        system: Optional[str],
    ) -> LLMResponse:
        try:
            import openai
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")

        api_key = self._api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise LLMError("No API key for OpenAI. Set OPENAI_API_KEY.")

        client = openai.AsyncOpenAI(api_key=api_key)
        full_messages = messages if not system else [{"role": "system", "content": system}] + messages
        response = await client.chat.completions.create(
            model=self.model_id,
            messages=full_messages,
            max_tokens=self.max_tokens,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            content=content,
            model_id=self.model_id,
            prompt_type=prompt_type,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=0,
        )


# Module-level singleton
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
