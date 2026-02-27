from __future__ import annotations

import os
from typing import Protocol, Sequence

from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

from execution.langgraph.state_schema import AgentMessage

load_dotenv()


class ChatProvider(Protocol):
    def generate(self, messages: Sequence[AgentMessage]) -> str:
        ...


class OpenAIChatProvider:
    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate(self, messages: Sequence[AgentMessage]) -> str:
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
    def __init__(self, model: str = "llama-3.3-70b-versatile") -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment.")
        self.client = Groq(api_key=api_key)
        self.model = model

    def generate(self, messages: Sequence[AgentMessage]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Model returned empty content.")
        return content


def build_provider(preferred: str = "openai") -> ChatProvider:
    preferred_normalized = preferred.lower().strip()
    if preferred_normalized == "groq":
        return GroqChatProvider()

    try:
        return OpenAIChatProvider()
    except ValueError:
        return GroqChatProvider()
