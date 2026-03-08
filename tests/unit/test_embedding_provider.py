"""Tests for EmbeddingProvider Protocol, MockEmbeddingProvider, FastEmbedProvider, get_embedding_provider().
Covers SCS-01, SCS-02 from VALIDATION.md.
"""
import logging
import math
import os

import pytest

from agentic_workflows.context.embedding_provider import (
    EmbeddingProvider,
    FastEmbedProvider,
    MockEmbeddingProvider,
    get_embedding_provider,
)


class TestMockEmbeddingProvider:
    def test_mock_dimensions(self):
        provider = MockEmbeddingProvider()
        assert provider.dimensions == 384

    def test_mock_determinism(self):
        provider = MockEmbeddingProvider()
        v1 = provider.embed_sync("hello world")
        v2 = provider.embed_sync("hello world")
        assert v1 == v2
        assert len(v1) == 384

    def test_mock_different_inputs(self):
        provider = MockEmbeddingProvider()
        v1 = provider.embed_sync("mission A")
        v2 = provider.embed_sync("mission B")
        assert v1 != v2

    def test_mock_unit_norm(self):
        provider = MockEmbeddingProvider()
        vec = provider.embed_sync("normalize test")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_mock_embed_batch(self):
        provider = MockEmbeddingProvider()
        results = provider.embed(["text a", "text b"])
        assert len(results) == 2
        assert all(len(r) == 384 for r in results)


class TestFastEmbedProvider:
    def test_import_guard(self):
        """FastEmbedProvider raises ImportError with helpful message when fastembed not installed."""
        try:
            import fastembed  # noqa: F401
            pytest.skip("fastembed is installed — import guard not triggered")
        except ImportError:
            pass
        with pytest.raises(ImportError, match="fastembed"):
            FastEmbedProvider()


class TestMockEmbeddingProviderLogging:
    def test_init_emits_embed_init_info(self, caplog):
        with caplog.at_level(logging.INFO, logger="embedding_provider"):
            MockEmbeddingProvider()
        assert any("EMBED INIT" in r.message and "provider=mock" in r.message for r in caplog.records)

    def test_embed_sync_emits_embed_gen_debug(self, caplog):
        provider = MockEmbeddingProvider()
        with caplog.at_level(logging.DEBUG, logger="embedding_provider"):
            provider.embed_sync("hello world")
        assert any("EMBED GEN" in r.message and "provider=mock" in r.message for r in caplog.records)

    def test_embed_gen_contains_dim(self, caplog):
        provider = MockEmbeddingProvider()
        with caplog.at_level(logging.DEBUG, logger="embedding_provider"):
            provider.embed_sync("test text")
        gen_records = [r for r in caplog.records if "EMBED GEN" in r.message]
        assert gen_records, "Expected EMBED GEN log record"
        assert "dim=384" in gen_records[0].message


class TestGetEmbeddingProvider:
    def test_env_routing_default(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        provider = get_embedding_provider()
        assert isinstance(provider, MockEmbeddingProvider)

    def test_env_routing_mock(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
        provider = get_embedding_provider()
        assert isinstance(provider, MockEmbeddingProvider)

    def test_env_routing_fastembed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
        try:
            import fastembed  # noqa: F401
            provider = get_embedding_provider()
            assert isinstance(provider, FastEmbedProvider)
        except ImportError:
            with pytest.raises(ImportError, match="fastembed"):
                get_embedding_provider()

    def test_env_routing_unknown_raises(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "unknown_provider")
        with pytest.raises(ValueError, match="unknown_provider"):
            get_embedding_provider()
