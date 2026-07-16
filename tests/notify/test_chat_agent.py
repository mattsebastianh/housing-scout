"""Tests for the gpt-5-nano Telegram chat agent."""

import json

import httpx
import pytest
import respx

from scout.core.notify.chat_agent import _FALLBACK, _OPENAI_URL, ChatAgent
from scout.core.profile import Profile, ProfileBuyer, ProfileCity, ProfileSearch

KNOWN = ["barcelona", "valencia", "girona"]


def _profile() -> Profile:
    return Profile(
        country="es",
        portal="idealista",
        search=ProfileSearch(
            cities=[
                ProfileCity(name=name, lat=0.0, lon=0.0, radius_km=30)
                for name in KNOWN
            ],
            price_min_eur=150_000,
            price_max_eur=250_000,
            property_type="chalet_independiente",
            preferred_plot_m2=600,
        ),
        buyer=ProfileBuyer(household="hogar de dos personas", response_language="es"),
    )


def _agent(api_key="sk-test"):
    return ChatAgent(profile=_profile(), api_key=api_key)


def _openai_response(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.mark.asyncio
async def test_reply_without_api_key_falls_back():
    """No OPENAI_API_KEY means a static help reply, never silence."""
    agent = _agent(api_key="")
    async with httpx.AsyncClient() as client:
        answer = await agent.reply("hola", client)
    assert answer == _FALLBACK
    assert "/scout" in answer


@pytest.mark.asyncio
async def test_reply_returns_model_text():
    """The model's answer comes back verbatim and the request carries context."""
    agent = _agent()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(
            return_value=_openai_response("¡Hola! ¿En qué te ayudo?")
        )
        async with httpx.AsyncClient() as client:
            answer = await agent.reply("hola", client)
    assert answer == "¡Hola! ¿En qué te ayudo?"
    payload = json.loads(route.calls[0].request.content)
    assert payload["model"] == "gpt-5-nano"
    assert payload["messages"][0]["role"] == "system"
    assert "barcelona" in payload["messages"][0]["content"]
    assert payload["messages"][-1] == {"role": "user", "content": "hola"}


@pytest.mark.asyncio
async def test_reply_keeps_rolling_history():
    """Earlier exchanges are replayed so the conversation stays coherent."""
    agent = _agent()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("ok"))
        async with httpx.AsyncClient() as client:
            await agent.reply("primera", client)
            await agent.reply("segunda", client)
    payload = json.loads(route.calls[1].request.content)
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert payload["messages"][1]["content"] == "primera"
    assert payload["messages"][-1]["content"] == "segunda"


@pytest.mark.asyncio
async def test_history_is_bounded():
    """History never grows past the cap (system + capped history + new user)."""
    agent = _agent()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("ok"))
        async with httpx.AsyncClient() as client:
            for i in range(20):
                await agent.reply(f"mensaje {i}", client)
    payload = json.loads(route.calls[-1].request.content)
    assert len(payload["messages"]) <= 1 + 12 + 1


@pytest.mark.asyncio
async def test_reply_api_error_falls_back_and_skips_history():
    """An OpenAI failure yields the fallback text and pollutes no history."""
    agent = _agent()
    with respx.mock:
        respx.post(_OPENAI_URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            answer = await agent.reply("hola", client)
        # next successful call must not replay the failed exchange
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("ok"))
        async with httpx.AsyncClient() as client:
            await agent.reply("otra", client)
    assert answer == _FALLBACK
    payload = json.loads(route.calls[-1].request.content)
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


@pytest.mark.asyncio
async def test_model_env_override(monkeypatch):
    """SCOUT_CHAT_MODEL swaps the brain without code changes."""
    monkeypatch.setenv("SCOUT_CHAT_MODEL", "gpt-5.4-nano")
    agent = _agent()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("ok"))
        async with httpx.AsyncClient() as client:
            await agent.reply("hola", client)
    assert json.loads(route.calls[0].request.content)["model"] == "gpt-5.4-nano"


def test_model_defaults_to_gpt5_nano(monkeypatch):
    """Without an override, the cheapest reasoning model is the default."""
    monkeypatch.delenv("SCOUT_CHAT_MODEL", raising=False)
    assert _agent()._model == "gpt-5-nano"


@pytest.mark.asyncio
async def test_context_note_injected_as_system_message():
    """A situational context note (e.g. run in progress) rides along as system."""
    agent = _agent()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("ok"))
        async with httpx.AsyncClient() as client:
            await agent.reply("¿ya está?", client, context="Hay una búsqueda en curso.")
    payload = json.loads(route.calls[0].request.content)
    assert payload["messages"][1]["role"] == "system"
    assert "búsqueda en curso" in payload["messages"][1]["content"]
