import os
import unittest
from unittest.mock import patch

from agentic_workflows.core.llm_provider import _resolve_ollama_base_url as p0_resolve
from agentic_workflows.orchestration.langgraph.provider import (
    _resolve_ollama_base_url as p1_resolve,
)


class ProviderConfigTests(unittest.TestCase):
    def test_explicit_base_url_wins(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://env:11434/v1"}, clear=True):
            self.assertEqual(p1_resolve("http://arg:11434/v1"), "http://arg:11434/v1")
            self.assertEqual(p0_resolve("http://arg:11434/v1"), "http://arg:11434/v1")

    def test_env_base_url_used_before_host(self) -> None:
        env = {
            "OLLAMA_BASE_URL": "http://env:11434/v1",
            "OLLAMA_HOST": "http://host:11434",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(p1_resolve(), "http://env:11434/v1")
            self.assertEqual(p0_resolve(), "http://env:11434/v1")

    def test_host_appends_v1_when_missing(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://host:11434"}, clear=True):
            self.assertEqual(p1_resolve(), "http://host:11434/v1")
            self.assertEqual(p0_resolve(), "http://host:11434/v1")

    def test_host_keeps_existing_v1(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://host:11434/v1/"}, clear=True):
            self.assertEqual(p1_resolve(), "http://host:11434/v1")
            self.assertEqual(p0_resolve(), "http://host:11434/v1")

    def test_default_url_when_none_set(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(p1_resolve(), "http://localhost:11434/v1")
            self.assertEqual(p0_resolve(), "http://localhost:11434/v1")


if __name__ == "__main__":
    unittest.main()
