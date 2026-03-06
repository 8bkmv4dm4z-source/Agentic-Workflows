from __future__ import annotations

"""Local agent configured for Ollama execution.

On initialisation the agent checks whether the active provider is
``OllamaChatProvider``.  If so, it calls :meth:`ensure_model` to create (once)
a custom Modelfile variant with the requested context window so Ollama never
silently truncates long prompts.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=ROOT_DIR / ".env")


class LocalAgent:
    """Agent preconfigured for local Ollama-backed runs.

    Parameters
    ----------
    num_ctx:
        Context window size passed to :meth:`OllamaChatProvider.ensure_model`.
        Defaults to the ``OLLAMA_NUM_CTX`` environment variable (or 32000).
    """

    def __init__(self, num_ctx: int | None = None) -> None:
        from agentic_workflows.orchestration.langgraph.provider import (
            OllamaChatProvider,
            build_provider,
        )

        self.provider = build_provider()

        if isinstance(self.provider, OllamaChatProvider):
            resolved_ctx = num_ctx if num_ctx is not None else int(os.getenv("OLLAMA_NUM_CTX", "32000"))
            self.model_name = self.provider.ensure_model(num_ctx=resolved_ctx)
        else:
            self.model_name = getattr(self.provider, "model", None)
