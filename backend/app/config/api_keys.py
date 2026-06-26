"""
Central place where every external API key is read from environment variables.

NOTHING in this file should ever contain a literal key. Real keys live in a
local `.env` file (gitignored) — see `.env.example` at the project root for the
list of variables to set. This module just loads and exposes them as constants
so the rest of the app never calls `os.getenv(...)` directly, which makes it
trivial to audit which keys the app actually uses.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from backend/app/config/).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_PROJECT_ROOT / ".env")

# --- LLM providers -----------------------------------------------------
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# --- STT providers -------------------------------------------------------
# Groq hosts Whisper too, so STT can reuse GROQ_API_KEY by default.
GROQ_WHISPER_API_KEY: str | None = os.getenv("GROQ_WHISPER_API_KEY", GROQ_API_KEY)

# --- Sarvam AI (STT + TTS, Indian-language tuned) -------------------------
SARVAM_API_KEY: str | None = os.getenv("SARVAM_API_KEY")

# --- TTS providers --------------------------------------------------------
ELEVENLABS_API_KEY: str | None = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID: str | None = os.getenv("ELEVENLABS_VOICE_ID")
GOOGLE_CLOUD_TTS_CREDENTIALS_PATH: str | None = os.getenv("GOOGLE_CLOUD_TTS_CREDENTIALS_PATH")


def require(key_value: str | None, key_name: str) -> str:
    """Raise a clear error at startup time if a required key is missing."""
    if not key_value:
        raise RuntimeError(
            f"Missing required API key: {key_name}. "
            f"Set it in your .env file (see .env.example)."
        )
    return key_value