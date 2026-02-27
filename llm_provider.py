# llm_provider.py

import os
from typing import List, Dict,cast
from groq import Groq
from groq.types.chat import ChatCompletionMessageParam

from dotenv import load_dotenv
from errors import LLMError
from agent_state import AgentMessage
from typing import Sequence

load_dotenv()


class LLMProvider:

    def __init__(self, model: str = "llama-3.3-70b-versatile"):

        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment.")

        self.client = Groq(api_key=api_key)
        self.model = model


    def generate(self, messages: Sequence[AgentMessage]) -> str:
        try:
            # Explicit boundary cast
            groq_messages = cast(
                Sequence[ChatCompletionMessageParam],
                messages
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=groq_messages,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            if content is None:
                raise LLMError("Model returned empty content.")

            return content

        except Exception as e:
            raise LLMError(str(e))