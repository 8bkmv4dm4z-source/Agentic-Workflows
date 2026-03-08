"""EmbeddingProvider Protocol, MockEmbeddingProvider, FastEmbedProvider, get_embedding_provider().

EMBEDDING_PROVIDER env var controls which provider is returned by get_embedding_provider():
  "mock" (default) — MockEmbeddingProvider, deterministic 384-dim, no download, CI-safe
  "fastembed"       — FastEmbedProvider, BAAI/bge-small-en-v1.5, ~24MB download on first use

The EmbeddingProvider Protocol defines the contract for any provider:
  embed(texts: list[str]) -> list[list[float]]
  embed_sync(text: str) -> list[float]
  dimensions: int property
"""
from __future__ import annotations

import hashlib
import os
import random
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Structural Protocol for embedding providers. Any duck-typed class satisfies this."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""
        ...

    def embed_sync(self, text: str) -> list[float]:
        """Embed a single text. Returns float vector of length self.dimensions."""
        ...

    @property
    def dimensions(self) -> int:
        """Number of dimensions in the embedding vector."""
        ...


class MockEmbeddingProvider:
    """Deterministic 384-dim embedding provider for CI and testing.

    Uses SHA-256 of input text as RNG seed — same text always produces the same
    unit-norm float vector, no model download required.
    """

    dimensions: int = 384

    def embed_sync(self, text: str) -> list[float]:
        """Embed a single text to a deterministic 384-dim unit-norm vector."""
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest(), "big")
        rng = random.Random(seed)
        vec = [rng.gauss(0, 1) for _ in range(self.dimensions)]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm > 0 else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        return [self.embed_sync(t) for t in texts]


class FastEmbedProvider:
    """ONNX-based embedding provider via fastembed (Qdrant).

    Uses BAAI/bge-small-en-v1.5 — 384-dim, CPU-native, ~24MB download on first use.
    Requires: pip install 'agentic-workflows[context]'
    """

    dimensions: int = 384

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from fastembed import TextEmbedding  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "fastembed is required for FastEmbedProvider. "
                "Install it: pip install 'agentic-workflows[context]' or pip install fastembed>=0.3"
            ) from exc
        self._model = TextEmbedding(model_name)
        self._model_name = model_name

    def embed_sync(self, text: str) -> list[float]:
        """Embed a single text. Wraps fastembed generator."""
        results = list(self._model.embed([text]))
        return [float(v) for v in results[0]]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        results = list(self._model.embed(texts))
        return [[float(v) for v in vec] for vec in results]


def get_embedding_provider() -> EmbeddingProvider:
    """Factory: returns the correct EmbeddingProvider based on EMBEDDING_PROVIDER env var.

    EMBEDDING_PROVIDER=mock (default) -> MockEmbeddingProvider
    EMBEDDING_PROVIDER=fastembed     -> FastEmbedProvider (requires fastembed installed)
    Any other value                  -> ValueError
    """
    provider_name = os.environ.get("EMBEDDING_PROVIDER", "mock").lower().strip()
    if provider_name == "mock":
        return MockEmbeddingProvider()
    if provider_name == "fastembed":
        return FastEmbedProvider()
    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER: {provider_name!r}. "
        "Valid values: 'mock', 'fastembed'"
    )
