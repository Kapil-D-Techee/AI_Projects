# Interactive AI Tutor (mini) — CBSE Class 9 Maths

> **This is the `Interactive-AI-Tutor-mini` branch/deployment** — active v2
> development (image upload for diagrams/graphs), built on top of the v1
> feature set below. Deployed separately for testing; intended to merge back
> into `main`/the primary deployment once stable.

A voice + text doubt-clarification tutor for CBSE Class 9 Maths (New Syllabus
2025-26), built around "Priya Ma'am" — a warm, experienced teacher persona
that guides students with hints before answers, in English or Tanglish
(Tamil Nadu code-mixed speech) depending on how the student talks.

## Architecture (v1)

```
Student mic/text -> FastAPI backend -> STT (Sarvam saaras:v3) -> LLM (OpenAI gpt-4o / gpt-4o-mini)
                                                                    |
                                            staged reply, split on ---CONTINUE---
                                            (Stage 1 = concept only; later stages
                                             held server-side until "Continue" is clicked)
                                                                    |
                                              math_speech normalizer (LaTeX -> spoken text)
                                                                    |
                                                      TTS (Sarvam bulbul:v3, ta-IN)
                                                                    |
                                                        audio reply played in browser
```

- **Push-to-talk, non-streaming** — no LiveKit. Student holds the mic button,
  releases, audio is sent once and transcribed. Simplest reliable path for v1.
- **STT/TTS default to Sarvam AI**, built specifically for Indian languages —
  `saaras:v3` (mode=codemix) handles Tamil/English code-mixed speech, and
  `bulbul:v3` (`ta-IN`) gives a native Tamil voice. ElevenLabs, OpenAI/Groq
  Whisper, and browser TTS remain available as one-line `.env` fallbacks.
- **LLM defaults to OpenAI** (`gpt-4o` or the cheaper `gpt-4o-mini`); Groq
  Llama 3.3 70B remains available via `LLM_PROVIDER=groq`.
- **Staged solutions** — the tutor gives the approach/concept first, not the
  full worked answer; the student clicks "Continue" to reveal each next step.
  A "+ New" button lets the student deliberately move on to a different
  problem without losing conversation context.
- **Every provider is swappable** without touching app logic — see
  `backend/app/config/providers.py` and `.env`.

## v2 (this branch): Image upload for diagrams/graphs

- A **(+) button** next to the text input lets a student attach a photo of a
  diagram/graph (e.g. from their NCERT textbook), with an optional typed
  caption asking a specific question about it (`POST /api/chat/image`).
- Vision-capable models only: works with `LLM_PROVIDER=openai`
  (`gpt-4o` / `gpt-4o-mini` both support image input via the same chat
  completions API). **Not supported on `LLM_PROVIDER=groq`** — the image
  endpoint raises a clear error rather than silently ignoring the picture.
- The tutor is instructed to describe what it sees in the image FIRST (so
  the student can correct a misread), then applies the SAME staged-solution
  (hints-first, `---CONTINUE---`) teaching method as text-based problems —
  image questions are not treated as a separate, simpler interaction.
- Images are capped at 8MB and `image/jpeg|png|webp|gif`; rejected with a
  clear 413/415 otherwise. The image itself is NOT stored in conversation
  history (to avoid bloating Redis with base64 blobs) — only a short text
  placeholder ("[Uploaded an image of a diagram/graph] <caption>") is kept,
  so later text turns still have conversational context.

## Project layout

```
backend/app/
  config/         api_keys.py (env loading), providers.py (vendor/model switches)
  prompts/        teacher_system_prompt.py (Priya Ma'am persona + CBSE syllabus)
  services/       stt_service.py, llm_service.py, tts_service.py,
                   math_speech.py (speakable-text conversion), session_store.py
  routes/         chat.py (FastAPI routes)
  main.py         FastAPI app entrypoint
frontend/
  templates/index.html, static/css/style.css, static/js/app.js
```

## Setup

```bash
# 1. Activate the existing Python 3.14 venv
.venv314\Scripts\activate        # Windows
# source .venv314/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
copy .env.example .env           # Windows
# cp .env.example .env           # macOS/Linux
# then edit .env and fill in GROQ_API_KEY and SARVAM_API_KEY at minimum

# 4. Run the server
uvicorn app.main:app --reload --app-dir backend
```

Open http://127.0.0.1:8000 in a browser. Allow microphone access to use
push-to-talk; typing works without mic permission.

## Required API keys

| Service               | Used for                                     | Get a key at         |
| --------------------- | --------------------------------------------- | -------------------- |
| OpenAI                | LLM (`gpt-4o` / `gpt-4o-mini`), default        | platform.openai.com  |
| Sarvam AI             | STT (saaras:v3) + TTS (bulbul:v3), default     | sarvam.ai            |
| Groq (optional)       | Alternate LLM (Llama 3.3 70B) / STT backend    | console.groq.com     |
| ElevenLabs (optional) | Alternate TTS backend                          | elevenlabs.io        |
| Upstash Redis         | Session storage on Vercel (free Marketplace tier) | vercel.com / upstash.com |

## Switching providers later

Edit `.env` (no code changes needed):

- `LLM_PROVIDER=openai` to switch LLM to `gpt-4o-mini` (or set `LLM_MODEL=gpt-4o`).
- `STT_PROVIDER=groq_whisper` or `openai_whisper` to move off Sarvam for STT.
- `TTS_PROVIDER=elevenlabs` or `browser` to move off Sarvam for TTS.
- `TTS_PROVIDER=google_cloud` once a Google Cloud TTS branch is added to
  `tts_service.py` (placeholder for native Tamil voice support).

## Deploying on Vercel

This is a standard FastAPI app deployed as a single Vercel Function.

1. **Connect an Upstash Redis integration** (Vercel dashboard → your project
   → Storage → Marketplace → Upstash Redis). This injects
   `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` automatically.
   Required in production — Vercel's Python runtime is serverless, so the
   in-memory fallback in `session_store.py` would lose conversation history
   and staged-solution progress unpredictably between requests.
2. **Set the rest of your `.env` values** as Environment Variables in the
   Vercel project settings (`GROQ_API_KEY`/`OPENAI_API_KEY`, `SARVAM_API_KEY`,
   `LLM_PROVIDER`, `LLM_MODEL`, etc. — same names as `.env.example`).
3. If this repo is a monorepo (this project lives in a subdirectory), set
   **Root Directory** to this folder when importing the project on Vercel.
4. Deploy. Vercel auto-detects Python via `requirements.txt` and uses
   `pyproject.toml`'s `tool.vercel.entrypoint` (`vercel_app:app`) to find the
   FastAPI app — see `vercel_app.py` for why a small shim module is needed
   (it puts `backend/` on `sys.path` so the existing `from app...` imports
   keep working unchanged from local dev).

## What's deferred to v2

- **Image upload / vision** — a student photographing a diagram from their
  textbook. v1 is text-only; no image input exists yet anywhere in the
  pipeline. When built, it should extend this same app (new route + a
  vision-capable model call in `llm_service.py`, new frontend upload
  control) rather than becoming a separate project, since the persona,
  prompt, and voice pipeline are all shared.
- **NCERT RAG** — chapter-grounded retrieval (NCERT PDFs + ChromaDB) is not
  yet wired in. The system prompt currently carries the full chapter list and
  teaching rules directly; retrieval-augmented chapter text is the next step
  once the core voice loop is validated with real student doubts.
- **Native Tamil TTS voice** — configurable via `SARVAM_LANGUAGE_CODE=ta-IN`
  (see `.env.example`), but English digit/idiom handling under that mode is
  still being tuned for natural-sounding Tanglish.
- Conversation logging/analytics and per-student daily token budgets are not
  yet implemented.

## Testing checklist before considering v1 done	

- [ ] Type a plain-English question, get a hint-first reply + audio.
- [ ] Type a Tanglish question, get a Tanglish reply (audio still English).
- [ ] Hold mic, ask a question aloud, verify transcript + reply + audio.
- [ ] Ask a question with `x^2`, `√`, `∠`, `°` in the reply — confirm audio
  speaks it naturally ("x squared", "root 2", "angle ABC", "60 degrees").
- [ ] Refuse-to-just-answer check: ask "what's the answer to Q5" directly —
  confirm it asks what you've tried first instead of solving immediately.
- [ ] Run through ~20 real CBSE Class 9 Maths doubts across chapters per the
  original test plan; tune `teacher_system_prompt.py` based on what feels
  unnatural or where the model gives the answer away too early.
