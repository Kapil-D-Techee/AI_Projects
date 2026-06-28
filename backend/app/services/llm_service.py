"""
LLM service — generates Priya Ma'am's reply given conversation history.
Default backend: Groq (Llama 3.3 70B Versatile). Swap to OpenAI by setting
LLM_PROVIDER=openai in .env; no other code needs to change.
"""
from __future__ import annotations

from groq import Groq
from openai import OpenAI

from app.config.api_keys import GROQ_API_KEY, OPENAI_API_KEY, require
from app.config.providers import LLM
from app.prompts.teacher_system_prompt import TEACHER_SYSTEM_PROMPT

ChatMessage = dict[str, str]  # {"role": "user" | "assistant", "content": "..."}


def _build_messages(history: list[ChatMessage]) -> list[ChatMessage]:
    return [{"role": "system", "content": TEACHER_SYSTEM_PROMPT}, *history]


async def generate_reply(history: list[ChatMessage]) -> str:
    """
    Given the running conversation (list of {"role", "content"} dicts, most
    recent student message last), return Priya Ma'am's next reply as text.
    """
    messages = _build_messages(history)

    if LLM.provider == "groq":
        client = Groq(api_key=require(GROQ_API_KEY, "GROQ_API_KEY"))
        completion = client.chat.completions.create(
            model=LLM.model,
            messages=messages,
            temperature=LLM.temperature,
            max_tokens=LLM.max_tokens,
        )
        return completion.choices[0].message.content.strip()

    if LLM.provider == "openai":
        client = OpenAI(api_key=require(OPENAI_API_KEY, "OPENAI_API_KEY"))
        completion = client.chat.completions.create(
            model=LLM.model,
            messages=messages,
            temperature=LLM.temperature,
            max_tokens=LLM.max_tokens,
        )
        return completion.choices[0].message.content.strip()

    raise NotImplementedError(f"Unknown LLM provider: {LLM.provider}")