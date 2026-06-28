"""
Text-to-speech service. Default backend: Sarvam AI (bulbul:v3) — native Indian
language voices, used to voice the teacher's reply. Defaults to ta-IN (Tamil)
for a genuinely native-sounding voice; override via SARVAM_LANGUAGE_CODE in
.env (e.g. "en-IN") if you want cleaner pronunciation of English/maths terms
instead. Note Sarvam speaks ONE language per request, so English words inside
a Tanglish sentence get a Tamil-accented reading under ta-IN — there's no way
to seamlessly code-switch the AUDIO itself; the on-screen text is always full
Tanglish regardless of which language the audio is in (see
math_speech.to_speech_text + the caller in routes/chat.py).
ElevenLabs Flash v2.5 remains available as a fallback (set TTS_PROVIDER=elevenlabs).

Swap to Google Cloud TTS by setting TTS_PROVIDER=google_cloud in .env and
adding a branch below.

NOTE on TTS_PROVIDER=browser: this is a frontend-only path (the browser's
built-in SpeechSynthesis API), used as a free fallback when no TTS API key
works (e.g. ElevenLabs free-tier accounts get a 402 on library voices). The
frontend checks GET /api/config and skips calling /api/chat/speak entirely in
that case, so this module is never invoked for that provider.
"""
from __future__ import annotations

import httpx
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

from app.config.api_keys import ELEVENLABS_API_KEY, SARVAM_API_KEY, require
from app.config.providers import TTS

_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs "Rachel" — warm, clear English voice
_DEFAULT_SARVAM_SPEAKER = "pooja"
_SARVAM_TTS_STREAM_URL = "https://api.sarvam.ai/text-to-speech/stream"
_SARVAM_MAX_CHARS = 2500  # bulbul:v3 limit; bulbul:v2 is 1500
# bulbul:v3's "temperature" controls expressiveness (0.01-2.0, API default
# 0.6 = fairly flat/stable). Raised here so Priya Ma'am's voice carries more
# warmth/emotion instead of sounding monotone; override via SARVAM_TEMPERATURE
# in .env if it sounds too unstable/exaggerated for a given speaker.
_DEFAULT_SARVAM_TEMPERATURE = 1.0


async def _synthesize_sarvam(speech_text: str) -> bytes:
    api_key = require(SARVAM_API_KEY, "SARVAM_API_KEY")
    text = speech_text[:_SARVAM_MAX_CHARS]
    payload = {
        "text": text,
        "target_language_code": TTS.language_code or "ta-IN",
        "speaker": TTS.voice_id or _DEFAULT_SARVAM_SPEAKER,
        "model": TTS.model,
        "pace": 1.0,
        "temperature": TTS.temperature if TTS.temperature is not None else _DEFAULT_SARVAM_TEMPERATURE,
        "speech_sample_rate": 22050,
        "output_audio_codec": "mp3",
    }
    headers = {"api-subscription-key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("POST", _SARVAM_TTS_STREAM_URL, headers=headers, json=payload) as response:
            response.raise_for_status()
            chunks = [chunk async for chunk in response.aiter_bytes()]
            return b"".join(chunks)


async def synthesize_speech(speech_text: str) -> bytes:
    """Convert speakable English text into MP3 audio bytes."""
    if TTS.provider == "sarvam":
        return await _synthesize_sarvam(speech_text)

    if TTS.provider == "elevenlabs":
        client = ElevenLabs(api_key=require(ELEVENLABS_API_KEY, "ELEVENLABS_API_KEY"))
        audio_stream = client.text_to_speech.convert(
            voice_id=TTS.voice_id or _DEFAULT_VOICE_ID,
            model_id=TTS.model,
            text=speech_text,
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
            output_format="mp3_44100_128",
        )
        return b"".join(audio_stream)

    raise NotImplementedError(f"Unknown TTS provider: {TTS.provider}")