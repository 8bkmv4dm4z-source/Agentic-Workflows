from __future__ import annotations

"""Provider adapters for Phase 1 planning model calls.

All runtime/provider selection comes from `.env`, and the graph uses one unified
`generate(messages)` provider contract regardless of vendor.
"""

import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import httpx
from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

from agentic_workflows.observability import observe
from agentic_workflows.orchestration.langgraph.state_schema import AgentMessage

# Phase 1 standardizes all provider/runtime config via repo-level .env.
ROOT_DIR = Path(__file__).resolve().parents[4]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0
DEFAULT_PROVIDER_MAX_RETRIES = 2
DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS = 1.0


class ProviderTimeoutError(RuntimeError):
    """Raised when provider calls repeatedly fail due to timeout/connection errors."""

    pass


def _resolve_ollama_base_url(base_url: str | None = None) -> str:
    """Resolve Ollama OpenAI-compatible endpoint from explicit args/env."""
    if base_url:
        return base_url
    explicit = os.getenv("OLLAMA_BASE_URL")
    if explicit:
        return explicit

    # Backward-compatible support for users who set OLLAMA_HOST.
    host = (os.getenv("OLLAMA_HOST") or "").strip().rstrip("/")
    if host:
        return host if host.endswith("/v1") else f"{host}/v1"
    return "http://localhost:11434/v1"


def _resolve_ollama_native_chat_url(base_url: str | None = None) -> str:
    """Resolve Ollama's native chat endpoint from explicit args/env."""
    resolved = _resolve_ollama_base_url(base_url).rstrip("/")
    if resolved.endswith("/api/chat"):
        return resolved
    if resolved.endswith("/v1"):
        resolved = resolved[: -len("/v1")]
    return f"{resolved}/api/chat"


class ChatProvider(Protocol):
    """Provider contract used by the LangGraph planner node."""

    def generate(self, messages: Sequence[AgentMessage]) -> str: ...


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _is_retryable_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "timeout",
        "timed out",
        "connection error",
        "connection reset",
        "temporarily unavailable",
        "service unavailable",
        "read timeout",
        "connect timeout",
    )
    return any(marker in text for marker in markers)


class _RetryingProviderBase:
    """Shared timeout/retry behavior for planner provider calls."""

    def __init__(self) -> None:
        self.timeout_seconds = _env_float(
            "P1_PROVIDER_TIMEOUT_SECONDS", DEFAULT_PROVIDER_TIMEOUT_SECONDS
        )
        self.max_retries = _env_int("P1_PROVIDER_MAX_RETRIES", DEFAULT_PROVIDER_MAX_RETRIES)
        self.retry_backoff_seconds = _env_float(
            "P1_PROVIDER_RETRY_BACKOFF_SECONDS",
            DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS,
        )

    def _request_with_retries(self, request_fn) -> object:  # noqa: ANN001
        attempts = self.max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return request_fn()
            except Exception as exc:  # noqa: BLE001
                if not _is_retryable_timeout_error(exc):
                    raise
                last_exc = exc
                if attempt >= attempts:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)
        raise ProviderTimeoutError(
            f"provider timeout after {attempts} attempts: {str(last_exc) if last_exc else 'unknown timeout'}"
        ) from last_exc


class OpenAIChatProvider(_RetryingProviderBase):
    """OpenAI-compatible provider using strict JSON responses."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment.")
        self.client = OpenAI(api_key=api_key, timeout=self.timeout_seconds)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        # Prefer structured JSON responses to reduce parse failures in the plan node.
        response = self._request_with_retries(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format={"type": "json_object"},
                timeout=self.timeout_seconds,
            )
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        return content


class GroqChatProvider(_RetryingProviderBase):
    """Groq provider path for users who prefer or already use Groq."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment.")
        self.client = Groq(api_key=api_key, timeout=self.timeout_seconds)
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        # Keep the same JSON-object response contract across providers.
        response = self._request_with_retries(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format={"type": "json_object"},
                timeout=self.timeout_seconds,
            )
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        return content


class OllamaChatProvider(_RetryingProviderBase):
    """Local Ollama provider for low-cost iterative development."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        super().__init__()
        resolved_model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        resolved_base_url = _resolve_ollama_base_url(base_url)
        self.model = resolved_model
        self.num_ctx = _env_int("OLLAMA_NUM_CTX", 0)
        self.use_native_chat_api = _env_bool(
            "OLLAMA_USE_NATIVE_CHAT_API",
            default=self.num_ctx > 0,
        )
        self.native_chat_url = (
            _resolve_ollama_native_chat_url(base_url) if self.use_native_chat_api else None
        )
        self.native_client = (
            httpx.Client(timeout=self.timeout_seconds) if self.use_native_chat_api else None
        )
        self.client = (
            None
            if self.use_native_chat_api
            else OpenAI(
                api_key="ollama",
                base_url=resolved_base_url,
                timeout=self.timeout_seconds,
            )
        )

    def _ollama_extra_body(self) -> dict | None:
        """Build Ollama-specific options passed via extra_body."""
        if self.num_ctx > 0:
            return {"options": {"num_ctx": self.num_ctx}}
        return None

    def _native_chat_payload(
        self,
        messages: Sequence[AgentMessage],
        *,
        json_mode: bool,
    ) -> dict:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
        }
        if self.num_ctx > 0:
            payload["options"] = {"num_ctx": self.num_ctx}
        if json_mode:
            payload["format"] = "json"
        return payload

    def _request_native_chat(
        self,
        messages: Sequence[AgentMessage],
        *,
        json_mode: bool,
    ) -> str:
        if self.native_client is None or self.native_chat_url is None:
            raise RuntimeError("Native Ollama client is not configured.")
        response = self.native_client.post(
            self.native_chat_url,
            json=self._native_chat_payload(messages, json_mode=json_mode),
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content")
        if content is None:
            raise ValueError("Model returned empty content.")
        return content

    @observe(name="provider.generate")
    def generate(self, messages: Sequence[AgentMessage]) -> str:
        if self.use_native_chat_api:
            try:
                return self._request_with_retries(
                    lambda: self._request_native_chat(messages, json_mode=True)
                )
            except Exception:
                return self._request_with_retries(
                    lambda: self._request_native_chat(messages, json_mode=False)
                )

        extra = self._ollama_extra_body()

        def _request_json_mode() -> object:
            if self.client is None:
                raise RuntimeError("Ollama OpenAI-compatible client is not configured.")
            return self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format={"type": "json_object"},
                timeout=self.timeout_seconds,
                **({"extra_body": extra} if extra else {}),
            )

        def _request_plain_mode() -> object:
            if self.client is None:
                raise RuntimeError("Ollama OpenAI-compatible client is not configured.")
            return self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                timeout=self.timeout_seconds,
                **({"extra_body": extra} if extra else {}),
            )

        try:
            # Try strict JSON mode first when the local OpenAI-compatible layer supports it.
            response = self._request_with_retries(_request_json_mode)
        except Exception:
            # Some local OpenAI-compatible adapters may not support response_format.
            response = self._request_with_retries(_request_plain_mode)
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        return content


def build_provider(preferred: str | None = None) -> ChatProvider:
    """Build provider from explicit argument or `P1_PROVIDER` env setting."""

    explicit_provider = preferred or os.getenv("P1_PROVIDER")
    if explicit_provider is not None:
        preferred_normalized = explicit_provider.lower().strip()
        if preferred_normalized == "groq":
            return GroqChatProvider()
        if preferred_normalized == "ollama":
            return OllamaChatProvider()
        if preferred_normalized == "openai":
            return OpenAIChatProvider()
        raise ValueError(
            f"Unsupported provider '{explicit_provider}'. "
            "Set P1_PROVIDER to one of: ollama, groq, openai."
        )

    for provider_cls in (OllamaChatProvider, OpenAIChatProvider, GroqChatProvider):
        try:
            return provider_cls()
        except ValueError:
            continue

    raise ValueError(
        "No provider is configured. Set P1_PROVIDER plus required env vars "
        "(OLLAMA_BASE_URL/OLLAMA_MODEL, OPENAI_API_KEY, or GROQ_API_KEY)."
    )
