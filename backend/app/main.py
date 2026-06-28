from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config.providers import LLM, STT, TTS
from app.routes.chat import router as chat_router

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"

app = FastAPI(title="Interactive AI Tutor — CBSE Class 9 Maths")

app.include_router(chat_router)
app.mount("/static", StaticFiles(directory=_FRONTEND_DIR / "static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "templates" / "index.html")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def client_config() -> dict[str, str]:
    """Tells the frontend which backends are active. The TTS provider also
    drives a real behavior switch (server-side audio vs. browser
    SpeechSynthesis); LLM/STT fields are exposed so it's easy to verify which
    model is actually answering the student, since this is configured via
    .env and not always obvious at a glance."""
    return {
        "tts_provider": TTS.provider,
        "llm_provider": LLM.provider,
        "llm_model": LLM.model,
        "stt_provider": STT.provider,
        "stt_model": STT.model,
    }