"""Conversational chat agent — gpt-5-nano replies to plain Telegram messages.

Plugged into the /scout listener so any non-command message from the
authorised chat gets an answer instead of silence. Keeps a small rolling
history per process for coherent back-and-forth; on any failure (no API key,
OpenAI error) it degrades to a static help reply, never to silence. The
system prompt is built from the profile-driven
``agent_instructions/chat_agent.md`` template (see
``scout.core.analyse.prompt_builder.build_system_prompt``).
"""

import os
from collections import deque

import httpx
import structlog

from scout.core.analyse.prompt_builder import build_system_prompt
from scout.core.profile import Profile

log = structlog.get_logger("notify.chat_agent")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# Cheapest reasoning-capable OpenAI model ($0.05/$0.40 per 1M tok as of 2026-07,
# vs $0.20/$1.25 for gpt-5.4-nano). Override with SCOUT_CHAT_MODEL.
_MODEL = "gpt-5-nano"
_REASONING_EFFORT = "minimal"  # chat replies should be snappy, not deliberative
_MAX_HISTORY = 12  # rolling messages kept as context (6 exchanges)

_FALLBACK = (
    "🤖 Ahora mismo no puedo responder con IA. "
    "Usa /scout para lanzar una búsqueda."
)


class ChatAgent:
    """Rolling-history chat brain for the authorised Telegram chat."""

    def __init__(
        self,
        *,
        profile: Profile,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self._model = model or os.environ.get("SCOUT_CHAT_MODEL") or _MODEL
        self._api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self._history: deque[dict] = deque(maxlen=_MAX_HISTORY)
        self._system = build_system_prompt("chat_agent", profile)

    async def reply(
        self, text: str, client: httpx.AsyncClient, *, context: str | None = None
    ) -> str:
        """Answer one user message; always returns something sendable."""
        if not self._api_key:
            return _FALLBACK
        messages = [{"role": "system", "content": self._system}]
        if context:
            messages.append({"role": "system", "content": context})
        messages += [*self._history, {"role": "user", "content": text}]
        try:
            answer = await self._complete(messages, client)
        except Exception as exc:
            log.warning("chat.failed", error=str(exc))
            return _FALLBACK
        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": answer})
        log.info("chat.replied", chars=len(answer))
        return answer

    async def _complete(self, messages: list[dict], client: httpx.AsyncClient) -> str:
        resp = await client.post(
            _OPENAI_URL,
            json={
                "model": self._model,
                "max_completion_tokens": 500,
                "reasoning_effort": _REASONING_EFFORT,
                "messages": messages,
            },
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
