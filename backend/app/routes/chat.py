"""
Routes for the voice/text tutoring loop:
  POST /api/chat/text         - text-only turn (typed question -> first stage's text + speech chunks)
  POST /api/chat/voice        - voice turn (recorded audio -> transcript + first stage's text + speech chunks)
  POST /api/chat/image        - image turn (uploaded diagram/graph + optional caption -> first stage's text + speech chunks)
  POST /api/chat/continue     - reveal the next held-back stage of a staged solution
  POST /api/chat/new_problem  - explicitly discard the current problem's held-back stages
  POST /api/chat/speak_chunk  - synthesize audio for ONE speech chunk (called per chunk by the frontend)
  POST /api/chat/speak        - synthesize audio for a whole text in one call (legacy/simple path)
  POST /api/chat/reset        - clear a session's conversation history

Staged solutions: the LLM is instructed (see teacher_system_prompt.py) to
split problem-solving answers into 2-3 stages separated by a literal
"---CONTINUE---" marker, so the student gets the concept/approach first and
has to attempt the problem before seeing further steps. chat_text/chat_voice/
chat_image only return Stage 1; later stages are held server-side in
session_store and revealed one at a time via /continue when the student
clicks the button.

A side question asked while a problem's stages are still pending (e.g. "wait
why is it 180 degrees again?") does NOT discard those pending stages — only a
genuinely new staged reply (one that itself contains ---CONTINUE---) replaces
them, or an explicit POST /api/chat/new_problem call (the "New" button) does.
This lets the student ask clarifying questions about the CURRENT problem
without losing their place in it.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.config.providers import TTS
from app.services import session_store
from app.services.llm_service import generate_reply, generate_reply_with_image
from app.services.math_speech import clean_display_text, split_into_speech_chunks, to_speech_text
from app.services.stt_service import transcribe_audio
from app.services.tts_service import synthesize_speech

router = APIRouter(prefix="/api/chat", tags=["chat"])

# True when the active TTS voice is Sarvam in a non-English (e.g. Tamil)
# language mode — that voice needs digits spelled out as English number
# words (it would otherwise read native-language numerals) and known
# Tanglish words respelled phonetically (e.g. "Sari" -> "Seari") to be
# pronounced correctly. English-target voices need neither.
_SARVAM_NON_ENGLISH_VOICE = TTS.provider == "sarvam" and (TTS.language_code or "").lower() != "en-in"

_CONTINUE_MARKER = "---CONTINUE---"


def _split_stages(reply: str) -> list[str]:
    stages = [s.strip() for s in reply.split(_CONTINUE_MARKER)]
    return [s for s in stages if s]


class TextTurnRequest(BaseModel):
    session_id: str
    message: str


class TurnResponse(BaseModel):
    session_id: str
    transcript: str | None = None  # only set for voice turns
    reply_text: str
    speech_chunks: list[str]  # reply_text split into TTS-sized pieces, in order
    has_more_stages: bool = False  # True -> frontend should show a "Continue" button


async def _process_llm_reply(session_id: str, reply: str) -> tuple[str, list[str], bool]:
    """
    Splits a fresh LLM reply on the ---CONTINUE--- marker and updates this
    session's pending stages, then returns (display_text, speech_chunks,
    has_more_stages) for the caller to build a response with.

    Only REPLACES pending stages when this reply itself is multi-stage (a new
    staged problem). A single-stage reply (e.g. answering a side question
    about a problem the student is already mid-solving) leaves any existing
    pending stages untouched, so a clarifying question doesn't make the
    student lose their place in the problem they were working on.

    speech_chunks are derived from the RAW stage text (to_speech_text does
    its own, more aggressive LaTeX-to-spoken-words conversion); display_text
    only gets the lighter clean_display_text pass, which unwraps LaTeX
    delimiters but keeps symbols like "°"/"×" as-is for on-screen reading.
    """
    stages = _split_stages(reply)
    first_stage = stages[0] if stages else reply

    if len(stages) > 1:
        await session_store.set_pending_stages(session_id, stages[1:])

    has_more = len(stages) > 1 or await session_store.has_pending_stages(session_id)
    speech_chunks = split_into_speech_chunks(first_stage)
    return clean_display_text(first_stage), speech_chunks, has_more


@router.post("/text", response_model=TurnResponse)
async def chat_text(payload: TextTurnRequest) -> TurnResponse:
    await session_store.append_turn(payload.session_id, "user", payload.message)
    reply = await generate_reply(await session_store.get_history(payload.session_id))
    await session_store.append_turn(payload.session_id, "assistant", reply)

    first_stage, speech_chunks, has_more = await _process_llm_reply(payload.session_id, reply)
    return TurnResponse(
        session_id=payload.session_id,
        reply_text=first_stage,
        speech_chunks=speech_chunks,
        has_more_stages=has_more,
    )


@router.post("/voice", response_model=TurnResponse)
async def chat_voice(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
) -> TurnResponse:
    audio_bytes = await audio.read()
    transcript = await transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")

    await session_store.append_turn(session_id, "user", transcript)
    reply = await generate_reply(await session_store.get_history(session_id))
    await session_store.append_turn(session_id, "assistant", reply)

    first_stage, speech_chunks, has_more = await _process_llm_reply(session_id, reply)
    return TurnResponse(
        session_id=session_id,
        transcript=transcript,
        reply_text=first_stage,
        speech_chunks=speech_chunks,
        has_more_stages=has_more,
    )


_MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8MB — generous for a phone photo of a textbook page
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post("/image", response_model=TurnResponse)
async def chat_image(
    session_id: str = Form(...),
    image: UploadFile = File(...),
    caption: str = Form(""),
) -> TurnResponse:
    """Image turn: student uploads a photo of a diagram/graph (e.g. from their
    NCERT textbook) via the (+) button, with an optional typed/spoken caption
    asking a specific question about it. Only works when LLM_PROVIDER=openai
    (gpt-4o / gpt-4o-mini are vision-capable; Groq's hosted text models here
    are not)."""
    image_bytes = await image.read()
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 8MB).")

    media_type = image.content_type or "image/jpeg"
    if media_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {media_type}")

    # Store a lightweight text placeholder in history (not the image bytes
    # themselves) so later text turns still have context like "what was that
    # diagram about?" without bloating session storage with base64 images.
    history_note = f"[Uploaded an image of a diagram/graph] {caption}".strip()
    await session_store.append_turn(session_id, "user", history_note)

    reply = await generate_reply_with_image(
        await session_store.get_history(session_id), image_bytes, media_type, caption
    )
    await session_store.append_turn(session_id, "assistant", reply)

    first_stage, speech_chunks, has_more = await _process_llm_reply(session_id, reply)
    return TurnResponse(
        session_id=session_id,
        reply_text=first_stage,
        speech_chunks=speech_chunks,
        has_more_stages=has_more,
    )


class ContinueRequest(BaseModel):
    session_id: str


class ContinueResponse(BaseModel):
    session_id: str
    reply_text: str
    speech_chunks: list[str]
    has_more_stages: bool = False


@router.post("/continue", response_model=ContinueResponse)
async def chat_continue(payload: ContinueRequest) -> ContinueResponse:
    next_stage, has_more = await session_store.pop_next_stage(payload.session_id)
    if next_stage is None:
        # Nothing pending (e.g. session reset, or double-click) — return an
        # empty stage rather than erroring, so the frontend can just hide the
        # Continue button quietly.
        return ContinueResponse(session_id=payload.session_id, reply_text="", speech_chunks=[])

    return ContinueResponse(
        session_id=payload.session_id,
        reply_text=clean_display_text(next_stage),
        speech_chunks=split_into_speech_chunks(next_stage),
        has_more_stages=has_more,
    )


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak_chunk")
async def chat_speak_chunk(payload: SpeakRequest) -> Response:
    """Synthesize audio for ONE speech chunk. The frontend calls this once per
    chunk from TurnResponse.speech_chunks so playback can start on the first
    chunk instead of waiting for the entire reply's audio (which, for a long
    multi-step solution, can take 30-50+ seconds in a single TTS call)."""
    speech_text = to_speech_text(
        payload.text,
        spell_out_numbers=_SARVAM_NON_ENGLISH_VOICE,
        respell_tanglish=_SARVAM_NON_ENGLISH_VOICE,
    )
    audio_bytes = await synthesize_speech(speech_text)
    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.post("/speak")
async def chat_speak(payload: SpeakRequest) -> Response:
    """Convert an entire text into one audio file in a single TTS call.
    Kept for simple/short text use; prefer /speak_chunk + speech_chunks from
    /text or /voice for anything that might be a long, multi-step reply."""
    speech_text = to_speech_text(
        payload.text,
        spell_out_numbers=_SARVAM_NON_ENGLISH_VOICE,
        respell_tanglish=_SARVAM_NON_ENGLISH_VOICE,
    )
    audio_bytes = await synthesize_speech(speech_text)
    return Response(content=audio_bytes, media_type="audio/mpeg")


class ResetRequest(BaseModel):
    session_id: str


@router.post("/reset")
async def chat_reset(payload: ResetRequest) -> dict[str, str]:
    await session_store.reset_session(payload.session_id)
    return {"status": "ok"}


class NewProblemRequest(BaseModel):
    session_id: str


@router.post("/new_problem")
async def chat_new_problem(payload: NewProblemRequest) -> dict[str, str]:
    """Explicitly discards the current problem's held-back stages (the
    'New' button) WITHOUT touching conversation history — Priya Ma'am still
    remembers what's been covered this session, but the student has signalled
    they're moving on from the current problem rather than continuing it."""
    await session_store.clear_pending_stages(payload.session_id)
    return {"status": "ok"}