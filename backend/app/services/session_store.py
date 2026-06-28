"""
Conversation history + pending-stages storage per session id.

Two backends, chosen automatically:
- Upstash Redis (via REST, using the `upstash-redis` client) when
  UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN are set in the
  environment — this is what Vercel injects once an Upstash Redis
  integration is connected to the project. Required in production because
  Vercel's Python runtime is serverless: each request can hit a different,
  possibly cold, function instance, so plain in-memory dicts would lose
  state unpredictably between requests.
- A plain in-memory dict otherwise, so local development (`uvicorn ...`)
  works with zero extra setup — no Redis account needed just to run the app
  on your own machine.

All functions are async so callers don't need to know which backend is
active; the in-memory backend just awaits nothing extra.
"""
from __future__ import annotations

import json
import os

MAX_TURNS_KEPT = 20  # cap history length to keep token usage/cost bounded

_HISTORY_PREFIX = "tutor:history:"
_STAGES_PREFIX = "tutor:stages:"

_USE_REDIS = bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))

if _USE_REDIS:
    from upstash_redis.asyncio import Redis

    _redis = Redis.from_env()
else:
    _redis = None

# In-memory fallback store, used only when _USE_REDIS is False.
_sessions: dict[str, list[dict[str, str]]] = {}
_pending_stages: dict[str, list[str]] = {}


async def get_history(session_id: str) -> list[dict[str, str]]:
    if _redis is not None:
        raw = await _redis.get(_HISTORY_PREFIX + session_id)
        return json.loads(raw) if raw else []
    return _sessions.setdefault(session_id, [])


async def append_turn(session_id: str, role: str, content: str) -> None:
    history = await get_history(session_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_TURNS_KEPT:
        del history[: len(history) - MAX_TURNS_KEPT]

    if _redis is not None:
        await _redis.set(_HISTORY_PREFIX + session_id, json.dumps(history))
    else:
        _sessions[session_id] = history


async def reset_session(session_id: str) -> None:
    if _redis is not None:
        await _redis.delete(_HISTORY_PREFIX + session_id)
        await _redis.delete(_STAGES_PREFIX + session_id)
    else:
        _sessions[session_id] = []
        _pending_stages.pop(session_id, None)


async def set_pending_stages(session_id: str, stages: list[str]) -> None:
    """Replace this session's held-back stages with a new set. Only call this
    when the latest reply genuinely produced new staged content (i.e. don't
    call it with an empty list just because the latest reply happened to be a
    single-stage side answer — that should leave existing pending stages
    alone; use clear_pending_stages() to explicitly clear instead)."""
    if not stages:
        return
    if _redis is not None:
        await _redis.set(_STAGES_PREFIX + session_id, json.dumps(stages))
    else:
        _pending_stages[session_id] = stages


async def has_pending_stages(session_id: str) -> bool:
    if _redis is not None:
        raw = await _redis.get(_STAGES_PREFIX + session_id)
        return bool(raw and json.loads(raw))
    return bool(_pending_stages.get(session_id))


async def clear_pending_stages(session_id: str) -> None:
    """Explicitly discard held-back stages — used by the 'New problem' action
    so the student can deliberately move on without finishing the current
    staged solution."""
    if _redis is not None:
        await _redis.delete(_STAGES_PREFIX + session_id)
    else:
        _pending_stages.pop(session_id, None)


async def pop_next_stage(session_id: str) -> tuple[str | None, bool]:
    """Returns (next_stage_text_or_None, has_more_after_this)."""
    if _redis is not None:
        raw = await _redis.get(_STAGES_PREFIX + session_id)
        stages: list[str] = json.loads(raw) if raw else []
    else:
        stages = _pending_stages.get(session_id, [])

    if not stages:
        return None, False

    next_stage = stages.pop(0)
    has_more = len(stages) > 0

    if _redis is not None:
        if has_more:
            await _redis.set(_STAGES_PREFIX + session_id, json.dumps(stages))
        else:
            await _redis.delete(_STAGES_PREFIX + session_id)
    else:
        if has_more:
            _pending_stages[session_id] = stages
        else:
            _pending_stages.pop(session_id, None)

    return next_stage, has_more
