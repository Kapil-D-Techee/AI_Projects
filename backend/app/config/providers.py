"""
Single source of truth for WHICH vendor/model backs each pipeline stage
(STT / LLM / TTS). Change a provider here (or override via env var) and every
service module picks it up — no code changes needed elsewhere.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Importing api_keys guarantees .env has been loaded into os.environ before we
# read provider/model env vars below, regardless of which module gets
# imported first elsewhere in the app.
from app.config import api_keys as _api_keys  # noqa: F401


@dataclass(frozen=True)
class LLMConfig:
    provider: str  # "groq" | "openai"
    model: str
    temperature: float = 0.6
    max_tokens: int = 700


@dataclass(frozen=True)
class STTConfig:
    provider: str  # "sarvam" | "groq_whisper" | "openai_whisper"
    model: str


@dataclass(frozen=True)
class TTSConfig:
    provider: str  # "sarvam" | "elevenlabs" | "google_cloud" | "browser"
    model: str
    voice_id: str | None = None  # ElevenLabs voice ID, or Sarvam speaker name (SARVAM_VOICE_NAME)
    language_code: str | None = None  # Sarvam target_language_code, e.g. "ta-IN" (SARVAM_LANGUAGE_CODE)
    temperature: float | None = None  # Sarvam expressiveness, 0.01-2.0 (SARVAM_TEMPERATURE)


# ---------------------------------------------------------------------------
# Defaults chosen for budget + latency fit for a voice tutoring app.
# Override any of these via environment variables without touching code.
#
# Model names are picked per-provider (not a single hardcoded default) so that
# switching LLM_PROVIDER/STT_PROVIDER alone (e.g. to "openai") gives a model
# name that actually exists on that vendor, without also having to remember
# to override LLM_MODEL/STT_MODEL by hand.
# ---------------------------------------------------------------------------

_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
_DEFAULT_LLM_MODEL = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
}.get(_LLM_PROVIDER, "llama-3.3-70b-versatile")

_STT_PROVIDER = os.getenv("STT_PROVIDER", "sarvam")
_DEFAULT_STT_MODEL = {
    "sarvam": "saaras:v3",
    "groq_whisper": "whisper-large-v3-turbo",
    "openai_whisper": "whisper-1",
}.get(_STT_PROVIDER, "saaras:v3")

_TTS_PROVIDER = os.getenv("TTS_PROVIDER", "sarvam")
_DEFAULT_TTS_MODEL = {
    "sarvam": "bulbul:v3",
    "elevenlabs": "eleven_flash_v2_5",
}.get(_TTS_PROVIDER, "bulbul:v3")
_DEFAULT_SARVAM_VOICE_NAME = "pooja"  # hardcoded fallback if SARVAM_VOICE_NAME is unset/blank
_DEFAULT_TTS_VOICE = {
    "sarvam": (os.getenv("SARVAM_VOICE_NAME") or _DEFAULT_SARVAM_VOICE_NAME).lower(),
    "elevenlabs": "21m00Tcm4TlvDq8ikWAM",
}.get(_TTS_PROVIDER)

LLM = LLMConfig(
    provider=_LLM_PROVIDER,
    model=os.getenv("LLM_MODEL", _DEFAULT_LLM_MODEL),
    temperature=float(os.getenv("LLM_TEMPERATURE", "0.6")),
    max_tokens=int(os.getenv("LLM_MAX_TOKENS", "700")),
)

STT = STTConfig(
    provider=_STT_PROVIDER,
    model=os.getenv("STT_MODEL", _DEFAULT_STT_MODEL),
)

# TTS_VOICE_ID is a generic override, only consulted for providers without
# their own dedicated voice env var (e.g. not for sarvam, which uses
# SARVAM_VOICE_NAME above instead).
_GENERIC_VOICE_ID = os.getenv("TTS_VOICE_ID") if _TTS_PROVIDER != "sarvam" else None
_ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID") if _TTS_PROVIDER == "elevenlabs" else None

TTS = TTSConfig(
    provider=_TTS_PROVIDER,
    model=os.getenv("TTS_MODEL", _DEFAULT_TTS_MODEL),
    voice_id=_GENERIC_VOICE_ID or _ELEVENLABS_VOICE_ID or _DEFAULT_TTS_VOICE,
    language_code=os.getenv("SARVAM_LANGUAGE_CODE") or "ta-IN",
    temperature=float(os.getenv("SARVAM_TEMPERATURE")) if os.getenv("SARVAM_TEMPERATURE") else None,
)