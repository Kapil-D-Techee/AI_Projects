"""
LLM service — generates Priya Ma'am's reply given conversation history.
Default backend: Groq (Llama 3.3 70B Versatile). Swap to OpenAI by setting
LLM_PROVIDER=openai in .env; no other code needs to change.

Image input (diagrams/graphs, v2): only supported on the OpenAI path, since
gpt-4o/gpt-4o-mini are vision-capable via the same chat completions API —
Groq's hosted text models here are not. generate_reply_with_image raises
NotImplementedError on the groq provider rather than silently ignoring the
image, so a misconfigured deployment fails loudly instead of pretending to
look at a picture it never saw.
"""
from __future__ import annotations

import base64

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


async def generate_reply_with_image(
    history: list[ChatMessage], image_bytes: bytes, image_media_type: str, caption: str
) -> str:
    """
    Same as generate_reply, but the latest user turn also includes an
    uploaded image (a photographed diagram/graph). `caption` is the
    student's optional typed/spoken text accompanying the image — may be
    empty if they uploaded with no question attached.
    """
    if LLM.provider != "openai":
        raise NotImplementedError(
            f"Image input is only supported with LLM_PROVIDER=openai, got '{LLM.provider}'."
        )

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_content = {
        "type": "image_url",
        "image_url": {"url": f"data:{image_media_type};base64,{image_b64}"},
    }
    text_content = {
        "type": "text",
        "text": caption or "Here's a photo of the diagram/graph I'm asking about.",
    }

    messages = [
        {"role": "system", "content": TEACHER_SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": [text_content, image_content]},
    ]

    client = OpenAI(api_key=require(OPENAI_API_KEY, "OPENAI_API_KEY"))
    completion = client.chat.completions.create(
        model=LLM.model,
        messages=messages,
        temperature=LLM.temperature,
        max_tokens=LLM.max_tokens,
    )
    return completion.choices[0].message.content.strip()