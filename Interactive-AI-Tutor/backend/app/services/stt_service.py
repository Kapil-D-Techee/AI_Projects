"""
Speech-to-text service. Default backend: Sarvam AI (saaras:v3, mode=codemix) —
purpose-built for Indian languages and handles Tamil/English code-mixed
(Tanglish) speech better than general-purpose Whisper models. Groq-hosted
Whisper and OpenAI Whisper remain available as fallbacks.

Swap providers by changing STT_PROVIDER in .env / backend/app/config/providers.py —
add a new branch in `transcribe_audio` if a new backend is introduced.
"""
from __future__ import annotations

import httpx
from groq import Groq
from openai import OpenAI

from app.config.api_keys import GROQ_WHISPER_API_KEY, OPENAI_API_KEY, SARVAM_API_KEY, require
from app.config.providers import STT

_SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"


def _groq_client() -> Groq:
    return Groq(api_key=require(GROQ_WHISPER_API_KEY, "GROQ_WHISPER_API_KEY / GROQ_API_KEY"))


def _openai_client() -> OpenAI:
    return OpenAI(api_key=require(OPENAI_API_KEY, "OPENAI_API_KEY"))


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    Transcribe recorded audio to text. Returns raw transcript (may be English,
    Tamil, or Tanglish — all three backends handle code-mixed speech
    reasonably well; we don't force a single `language` param so the model
    can auto-detect / code-mix).
    """
    if STT.provider == "sarvam":
        api_key = require(SARVAM_API_KEY, "SARVAM_API_KEY")
        form_data = {"model": STT.model, "language_code": "unknown"}
        if STT.model.startswith("saaras"):
            # "codemix" (Tamil/English mixed transcription) is only a valid
            # mode for the saaras family; saarika doesn't accept it.
            form_data["mode"] = "codemix"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _SARVAM_STT_URL,
                headers={"api-subscription-key": api_key},
                files={"file": (filename, audio_bytes)},
                data=form_data,
            )
            response.raise_for_status()
            return response.json()["transcript"].strip()

    if STT.provider == "groq_whisper":
        client = _groq_client()
        transcription = client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=STT.model,
            response_format="text",
        )
        # Groq SDK returns either a str or an object depending on response_format.
        return str(transcription).strip()

    if STT.provider == "openai_whisper":
        client = _openai_client()
        transcription = client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=STT.model,
            response_format="text",
        )
        return str(transcription).strip()

    raise NotImplementedError(f"Unknown STT provider: {STT.provider}")