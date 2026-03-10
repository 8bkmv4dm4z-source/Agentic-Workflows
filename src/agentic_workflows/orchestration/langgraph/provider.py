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

from agentic_workflows.logger import get_logger
from agentic_workflows.observability import observe
from agentic_workflows.orchestration.langgraph.state_schema import AgentMessage

_LOG = get_logger("langgraph.provider")

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

    def generate(
        self,
        messages: Sequence[AgentMessage],
        response_schema: dict | None = None,
    ) -> str: ...

    def context_size(self) -> int: ...


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
        "http 500",
        "status code 500",
        "context length exceeded",
        "context window",
        "request entity too large",
        "payload too large",
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
                _LOG.warning(
                    "PROVIDER RETRY attempt=%d/%d error=%s",
                    attempt, attempts, exc,
                )
                time.sleep(self.retry_backoff_seconds * attempt)
        _LOG.error(
            "PROVIDER TIMEOUT after %d attempts: %s",
            attempts, str(last_exc) if last_exc else "unknown",
        )
        raise ProviderTimeoutError(
            f"provider timeout after {attempts} attempts: {str(last_exc) if last_exc else 'unknown timeout'}"
        ) from last_exc


# JSON Schema response format for OpenAI — guides the model toward the expected action shape.
# Non-strict (strict omitted) to allow flexible `args` objects without recursive constraints.
_OPENAI_ACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_action",
        "description": "An agent action: tool call, finish, or clarify",
        "schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["tool", "finish", "clarify"],
                },
                "tool_name": {"type": "string"},
                "args": {"type": "object"},
                "answer": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": True,
        },
    },
}


class OpenAIChatProvider(_RetryingProviderBase):
    """OpenAI-compatible provider using schema-guided JSON responses."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment.")
        self.client = OpenAI(api_key=api_key, timeout=self.timeout_seconds)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def context_size(self) -> int:
        return 128000

    def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
        # Use json_schema response format to guide the model toward the expected action shape.
        # Falls back to json_object if the model does not support json_schema.
        schema_to_use = response_schema if response_schema is not None else _OPENAI_ACTION_RESPONSE_FORMAT

        def _request_schema_mode() -> object:
            return self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format=schema_to_use,
                timeout=self.timeout_seconds,
            )

        def _request_json_mode() -> object:
            return self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format={"type": "json_object"},
                timeout=self.timeout_seconds,
            )

        try:
            response = self._request_with_retries(_request_schema_mode)
        except Exception:
            response = self._request_with_retries(_request_json_mode)
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

    def context_size(self) -> int:
        return 32768

    def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
        # response_schema ignored -- Groq has limited json_schema support
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
        # Per-provider timeout override: magistral and other reasoning models need more time.
        ollama_timeout = _env_float("OLLAMA_TIMEOUT", 0.0)
        if ollama_timeout > 0:
            self.timeout_seconds = ollama_timeout
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

    def context_size(self) -> int:
        return self.num_ctx if self.num_ctx > 0 else int(os.getenv("OLLAMA_NUM_CTX", "32768"))

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
    def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
        # response_schema ignored -- Ollama does not support json_schema response_format
        if self.use_native_chat_api:
            try:
                result = self._request_with_retries(
                    lambda: self._request_native_chat(messages, json_mode=True)
                )
                if result:
                    return result
                # json_mode returned empty — fall through to plain mode
            except Exception:
                pass
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
        # json_mode can force empty output on some models — retry in plain mode
        if not content:
            try:
                response = self._request_with_retries(_request_plain_mode)
                content = response.choices[0].message.content or ""
            except Exception:
                pass
        return content


    def _ollama_native_base(self) -> str:
        """Return the Ollama native API base URL (e.g. http://localhost:11434)."""
        if self.native_chat_url:
            return self.native_chat_url.rstrip("/").removesuffix("/api/chat")
        resolved = _resolve_ollama_base_url().rstrip("/")
        if resolved.endswith("/v1"):
            resolved = resolved[:-3]
        return resolved

    def ensure_model(self, num_ctx: int = 32000) -> str:
        """Ensure a custom Modelfile-backed model with the correct context window exists.

        Derives a safe name from the base model (e.g. ``"magistral"`` →
        ``"magistral-32k"``, ``"qwen3:8b"`` → ``"qwen3-8b-32k"``), checks
        ``GET /api/tags`` for an existing model, and creates one via
        ``POST /api/create`` if absent.  Updates ``self.model`` to the custom
        name and returns it.
        """
        base_model = self.model
        k_label = f"{num_ctx // 1000}k"
        custom_name = f"{base_model.replace(':', '-')}-{k_label}"

        native_base = self._ollama_native_base()
        client = httpx.Client(timeout=30.0)
        try:
            tags_resp = client.get(f"{native_base}/api/tags")
            tags_resp.raise_for_status()
            # Tags can appear as "name:latest" even when created without a tag.
            existing: set[str] = set()
            for m in tags_resp.json().get("models", []):
                n: str = m["name"]
                existing.add(n)
                existing.add(n.split(":")[0])

            if custom_name not in existing:
                create_resp = client.post(
                    f"{native_base}/api/create",
                    json={
                        "model": custom_name,
                        "from": base_model,
                        "parameters": {"num_ctx": num_ctx},
                    },
                    timeout=300.0,
                )
                create_resp.raise_for_status()
        finally:
            client.close()

        self.model = custom_name
        return custom_name


# Minimal GBNF grammar that constrains llama-server output to valid JSON objects.
# Passed via extra_body so token sampling physically cannot emit malformed JSON.
# Note: GBNF does not support {n} quantifiers — unicode escapes use four explicit groups.
_JSON_GBNF_GRAMMAR = r'''root   ::= object
value  ::= object | array | string | number | "true" | "false" | "null"
object ::= "{" ws (string ":" ws value ("," ws string ":" ws value)*)? "}" ws
array  ::= "[" ws (value ("," ws value)*)? "]" ws
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\" "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\"" ws
number ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws
ws     ::= ([ \t\n] ws)?
'''


def _detect_llama_cpp_model(base_url: str) -> str | None:
    """Query the running llama-server for the loaded model name.

    Calls GET /v1/models and returns the first model ID, or None on failure.
    Useful when LLAMA_CPP_MODEL=auto so the .env doesn't need updating every
    time a different GGUF is loaded into llama-server.
    """
    try:
        normalized = base_url.rstrip("/")
        if not normalized.endswith("/v1"):
            normalized += "/v1"
        resp = httpx.get(f"{normalized}/models", timeout=3.0)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if models:
            return str(models[0]["id"])
    except Exception:  # noqa: BLE001
        pass
    return None


class LlamaCppChatProvider(_RetryingProviderBase):
    """Local llama-server (SYCL/CPU) provider via its OpenAI-compatible endpoint.

    Set LLAMA_CPP_MODEL=auto (the default) to let the provider query the server
    at startup and use whatever model is currently loaded — no .env edit needed
    when switching GGUFs.  Set it to a specific filename to pin a model name.

    JSON output is enforced via GBNF grammar passed in extra_body, which
    constrains token sampling at the server level so the model physically cannot
    emit malformed JSON regardless of instruction-following quality.
    """

    # Recommended GGUF models for CPU / Intel Arc (update LLAMA_CPP_MODEL=auto
    # to use whichever is currently loaded, or pin one of these):
    #
    #   Qwen2.5-7B-Instruct-Q4_K_M.gguf   — best JSON discipline, ~4.5 GB
    #   Qwen2.5-7B-Instruct-Q5_K_M.gguf   — slightly better quality, ~5.4 GB
    #   Qwen3-4B-Q4_K_M.gguf              — newest Qwen, strong tool-use, ~2.5 GB
    #   Qwen3-4B-Q5_K_M.gguf              — recommended if 3 GB available
    #   Llama-3.1-8B-Instruct-Q4_K_M.gguf — solid fallback, ~4.7 GB
    #   Llama-3.2-3B-Instruct-Q5_K_M.gguf — fastest CPU option, ~2.3 GB
    #   phi-4-Q4_K_M.gguf                 — Microsoft Phi-4, strong reasoning
    #
    # Download from HuggingFace:
    #   huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF --include "*Q4_K_M*"
    #   huggingface-cli download Qwen/Qwen3-4B-GGUF --include "*Q4_K_M*"
    #   huggingface-cli download bartowski/Meta-Llama-3.1-8B-Instruct-GGUF --include "*Q4_K_M*"
    #   huggingface-cli download bartowski/Llama-3.2-3B-Instruct-GGUF --include "*Q5_K_M*"

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        super().__init__()
        llama_cpp_timeout = _env_float("LLAMA_CPP_TIMEOUT", 0.0)
        if llama_cpp_timeout > 0:
            self.timeout_seconds = llama_cpp_timeout
        resolved_base_url = base_url or os.getenv(
            "LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080/v1"
        )
        env_model = model or os.getenv("LLAMA_CPP_MODEL", "auto")
        if env_model.lower() == "auto":
            detected = _detect_llama_cpp_model(resolved_base_url)
            self.model = detected or "local"
            if detected:
                _LOG.info("LLAMA-CPP AUTO-DETECTED model=%s url=%s", detected, resolved_base_url)
            else:
                _LOG.warning(
                    "LLAMA-CPP model detection failed (server not running?), using 'local'"
                )
        else:
            self.model = env_model
        self.client = OpenAI(
            api_key="llama-cpp",
            base_url=resolved_base_url,
            timeout=self.timeout_seconds,
        )
        # Grammar enforcement: disabled per-request when LLAMA_CPP_GRAMMAR=false
        self._grammar_enabled = os.getenv("LLAMA_CPP_GRAMMAR", "true").strip().lower() not in (
            "0", "false", "no"
        )

    def context_size(self) -> int:
        return int(os.getenv("LLAMA_CPP_N_CTX", "8192"))

    @observe(name="provider.generate")
    def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
        enable_thinking = os.getenv("LLAMA_CPP_THINKING", "").strip().lower() in ("1", "true", "yes")
        extra: dict = {"enable_thinking": True} if enable_thinking else {}

        # Grammar enforcement: merge GBNF grammar into extra_body so llama-server
        # constrains token sampling to valid JSON objects at the sampler level.
        if self._grammar_enabled:
            extra = {**extra, "grammar": _JSON_GBNF_GRAMMAR}

        # Qwen3 /no_think suffix: append to last user message when thinking is off.
        # This is the most reliable way to suppress Qwen3's extended reasoning mode.
        prepared = list(messages)
        if not enable_thinking:
            for i in range(len(prepared) - 1, -1, -1):
                msg = prepared[i]
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and not content.rstrip().endswith("/no_think"):
                        prepared[i] = {**msg, "content": content.rstrip() + " /no_think"}
                    break

        def _request_json_mode() -> object:
            # When GBNF grammar is active it supersedes response_format — llama-server
            # treats them as mutually exclusive and returns 500 if both are present.
            # Grammar-enforced sampling is strictly stronger than json_object mode,
            # so skip response_format when grammar is already in extra_body.
            kwargs: dict = {
                "model": self.model,
                "messages": prepared,
                "timeout": self.timeout_seconds,
            }
            if not self._grammar_enabled:
                kwargs["response_format"] = response_schema if response_schema is not None else {"type": "json_object"}
            if extra:
                kwargs["extra_body"] = extra
            return self.client.chat.completions.create(**kwargs)

        def _request_plain_mode() -> object:
            return self.client.chat.completions.create(
                model=self.model,
                messages=prepared,
                timeout=self.timeout_seconds,
                extra_body=extra if extra else None,
            )

        try:
            response = self._request_with_retries(_request_json_mode)
        except Exception:
            response = self._request_with_retries(_request_plain_mode)
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        if not content:
            try:
                response = self._request_with_retries(_request_plain_mode)
                content = response.choices[0].message.content or ""
            except Exception:
                pass
        # Grammar-induced semantic collapse: GBNF grammar allows "{}" as the minimum
        # valid JSON object token sequence.  Some models (e.g. phi-4) return bare "{}"
        # when grammar-constrained inference fails to follow the action schema.
        # Fall back to plain (unconstrained) mode so the model can use the system
        # prompt's JSON examples instead of grammar-guided sampling.
        if self._grammar_enabled and content.strip() == "{}":
            _LOG.warning(
                "LLAMA-CPP grammar returned '{}' — falling back to plain mode for model=%s",
                self.model,
            )
            try:
                response = self._request_with_retries(_request_plain_mode)
                plain_content = response.choices[0].message.content
                if plain_content:
                    content = plain_content
            except Exception:  # noqa: BLE001
                pass
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
        if preferred_normalized == "llama-cpp":
            return LlamaCppChatProvider()
        raise ValueError(
            f"Unsupported provider '{explicit_provider}'. "
            "Set P1_PROVIDER to one of: ollama, groq, openai, llama-cpp."
        )

    fallback_classes: list[type] = [OllamaChatProvider, OpenAIChatProvider, GroqChatProvider]
    if os.getenv("LLAMA_CPP_BASE_URL"):
        fallback_classes.append(LlamaCppChatProvider)

    for provider_cls in fallback_classes:
        try:
            return provider_cls()
        except ValueError:
            continue

    raise ValueError(
        "No provider is configured. Set P1_PROVIDER plus required env vars "
        "(OLLAMA_BASE_URL/OLLAMA_MODEL, OPENAI_API_KEY, GROQ_API_KEY, "
        "or LLAMA_CPP_BASE_URL)."
    )
