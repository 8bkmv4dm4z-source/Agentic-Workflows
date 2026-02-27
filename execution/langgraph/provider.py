from __future__ import annotations

"""Provider adapters for Phase 1 planning model calls.

All runtime/provider selection comes from `.env`, and the graph uses one unified
`generate(messages)` provider contract regardless of vendor.
"""

import os
from pathlib import Path
from typing import Protocol, Sequence

from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

from execution.langgraph.state_schema import AgentMessage

# Phase 1 standardizes all provider/runtime config via repo-level .env.
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT_DIR / ".env")


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


class ChatProvider(Protocol):
    """Provider contract used by the LangGraph planner node."""

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        ...


class OpenAIChatProvider:
    """OpenAI-compatible provider using strict JSON responses."""

    def __init__(self, model: str | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment.")
        self.client = OpenAI(api_key=api_key)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        # Prefer structured JSON responses to reduce parse failures in the plan node.
        response = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        return content


class GroqChatProvider:
    """Groq provider path for users who prefer or already use Groq."""

    def __init__(self, model: str | None = None) -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment.")
        self.client = Groq(api_key=api_key)
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        # Keep the same JSON-object response contract across providers.
        response = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        return content


class OllamaChatProvider:
    """Local Ollama provider for low-cost iterative development."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        resolved_model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        resolved_base_url = _resolve_ollama_base_url(base_url)
        self.client = OpenAI(api_key="ollama", base_url=resolved_base_url)
        self.model = resolved_model

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        try:
            # Try strict JSON mode first when the local OpenAI-compatible layer supports it.
            response = self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format={"type": "json_object"},
            )
        except Exception:
            # Some local OpenAI-compatible adapters may not support response_format.
            response = self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
            )
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
