# llm_provider.py

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

from agentic_workflows.core.agent_state import AgentMessage
from agentic_workflows.errors import LLMError

ROOT_DIR = Path(__file__).resolve().parents[1]
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


class LLMProvider:
    """Provider adapter for the non-LangGraph orchestrator.

    Provider selection order:
    1) explicit constructor arg `provider`
    2) `LLM_PROVIDER` from environment
    3) `P1_PROVIDER` from environment
    4) default: `ollama`
    """

    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
    ) -> None:
        provider_name = (
            (provider or os.getenv("LLM_PROVIDER") or os.getenv("P1_PROVIDER") or "ollama")
            .lower()
            .strip()
        )

        if provider_name == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("GROQ_API_KEY not found in environment.")
            self.client = Groq(api_key=api_key)
            self.model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        elif provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found in environment.")
            self.client = OpenAI(api_key=api_key)
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        elif provider_name == "ollama":
            resolved_base_url = _resolve_ollama_base_url(base_url)
            self.client = OpenAI(api_key="ollama", base_url=resolved_base_url)
            self.model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        else:
            raise ValueError(
                "Unsupported provider. Set LLM_PROVIDER/P1_PROVIDER to one of: ollama, groq, openai."
            )

        self.provider_name = provider_name

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        try:
            if self.provider_name == "ollama":
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=list(messages),
                        response_format={"type": "json_object"},
                    )
                except Exception:
                    # Some local OpenAI-compatible layers do not support response_format.
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=list(messages),
                    )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=list(messages),
                    response_format={"type": "json_object"},
                )

            content = response.choices[0].message.content
            if content is None:
                raise LLMError("Model returned empty content.")
            return content
        except Exception as e:
            raise LLMError(str(e)) from e
