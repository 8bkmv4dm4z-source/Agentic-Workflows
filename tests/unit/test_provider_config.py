import os
import unittest
from unittest.mock import Mock, patch

from agentic_workflows.core.llm_provider import _resolve_ollama_base_url as p0_resolve
from agentic_workflows.orchestration.langgraph.provider import (
    OllamaChatProvider,
    _resolve_ollama_native_chat_url,
)
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

    def test_native_chat_url_strips_v1_suffix(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://env:11434/v1"}, clear=True):
            self.assertEqual(
                _resolve_ollama_native_chat_url(),
                "http://env:11434/api/chat",
            )
            self.assertEqual(
                _resolve_ollama_native_chat_url("http://arg:11434/v1"),
                "http://arg:11434/api/chat",
            )

    def test_ollama_provider_uses_native_chat_when_num_ctx_enabled(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": '{"answer":"ok"}'}}
        native_client = Mock()
        native_client.post.return_value = response

        with (
            patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8192"}, clear=True),
            patch(
                "agentic_workflows.orchestration.langgraph.provider.httpx.Client",
                return_value=native_client,
            ),
            patch("agentic_workflows.orchestration.langgraph.provider.OpenAI") as openai_client,
        ):
            provider = OllamaChatProvider(model="qwen-test", base_url="http://host:11434/v1")
            result = provider.generate([{"role": "user", "content": "hello"}])

        self.assertEqual(result, '{"answer":"ok"}')
        openai_client.assert_not_called()
        native_client.post.assert_called_once()
        self.assertEqual(native_client.post.call_args.args[0], "http://host:11434/api/chat")
        self.assertEqual(
            native_client.post.call_args.kwargs["json"],
            {
                "model": "qwen-test",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
                "options": {"num_ctx": 8192},
                "format": "json",
            },
        )

    def test_ollama_provider_can_force_compat_mode(self) -> None:
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"answer":"ok"}'))]
        compat_client = Mock()
        compat_client.chat.completions.create.return_value = response

        with (
            patch.dict(
                os.environ,
                {
                    "OLLAMA_NUM_CTX": "8192",
                    "OLLAMA_USE_NATIVE_CHAT_API": "false",
                },
                clear=True,
            ),
            patch(
                "agentic_workflows.orchestration.langgraph.provider.OpenAI",
                return_value=compat_client,
            ),
            patch(
                "agentic_workflows.orchestration.langgraph.provider.httpx.Client"
            ) as native_client,
        ):
            provider = OllamaChatProvider(model="qwen-test", base_url="http://host:11434/v1")
            result = provider.generate([{"role": "user", "content": "hello"}])

        self.assertEqual(result, '{"answer":"ok"}')
        native_client.assert_not_called()
        compat_client.chat.completions.create.assert_called_once()
        self.assertEqual(
            compat_client.chat.completions.create.call_args.kwargs["extra_body"],
            {"options": {"num_ctx": 8192}},
        )


if __name__ == "__main__":
    unittest.main()
