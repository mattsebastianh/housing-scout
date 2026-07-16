"""Tests for the Property AI Analyst — model selection and response handling."""

import json
from datetime import datetime, UTC

import httpx
import pytest
import respx

from scout.core.analyse.property_analyst import _OPENAI_URL, analyse_top
from scout.core.models import Listing, ScoredListing
from scout.core.profile import Profile, ProfileBuyer, ProfileCity, ProfileSearch


def _make_profile() -> Profile:
    return Profile(
        country="es",
        portal="idealista",
        search=ProfileSearch(
            cities=[ProfileCity(name="valencia", lat=39.47, lon=-0.38, radius_km=30)],
            price_min_eur=150_000,
            price_max_eur=250_000,
            property_type="chalet_independiente",
            preferred_plot_m2=600,
        ),
        buyer=ProfileBuyer(household="hogar de dos personas", response_language="es"),
    )


def _make_scored():
    l = Listing(
        portal="idealista",
        external_id="111",
        city="valencia",
        url="https://www.idealista.com/inmueble/111/",
        price_eur=215_000,
        size_m2=120,
        bedrooms=3,
        bathrooms=2,
        municipality="Torrent",
        province="Valencia",
        address=None,
        lat=39.4,
        lon=-0.5,
        description="Chalet independiente con parcela.",
        days_on_market=10,
        cadastral_ref=None,
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )
    return ScoredListing(
        listing=l,
        dim_scores={"price": 7.0, "location": 8.0},
        composite=7.5,
        positives_md="",
        risks_md="",
    )


def _openai_response(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.mark.asyncio
async def test_analyse_top_uses_default_model(monkeypatch):
    """Without an override, the analyst asks gpt-5.4-mini."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("SCOUT_ANALYST_MODEL", raising=False)
    scored = _make_scored()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(
            return_value=_openai_response("RESUMEN: Buena conexión.\n\nAnálisis detallado.")
        )
        await analyse_top([scored], _make_profile())
    payload = json.loads(route.calls[0].request.content)
    assert payload["model"] == "gpt-5.4-mini"
    assert payload["reasoning_effort"] == "low"
    # format-preservation: the analyst still splits the model output on
    # "RESUMEN:" into summary_md / analyst_md — this contract is untouched.
    assert scored.summary_md == "Buena conexión."
    assert "Análisis detallado." in scored.analyst_md


@pytest.mark.asyncio
async def test_analyse_top_splits_on_english_summary_marker(monkeypatch):
    """The English template's "SUMMARY:" marker is split the same way as "RESUMEN:"."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    scored = _make_scored()
    with respx.mock:
        respx.post(_OPENAI_URL).mock(
            return_value=_openai_response("SUMMARY: Good connectivity.\n\nDetailed analysis.")
        )
        await analyse_top([scored], _make_profile())
    assert scored.summary_md == "Good connectivity."
    assert "Detailed analysis." in scored.analyst_md


@pytest.mark.asyncio
async def test_analyse_top_model_env_override(monkeypatch):
    """SCOUT_ANALYST_MODEL swaps the analyst brain without code changes."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SCOUT_ANALYST_MODEL", "gpt-5.4")
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("RESUMEN: ok"))
        await analyse_top([_make_scored()], _make_profile())
    assert json.loads(route.calls[0].request.content)["model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_analyse_top_skips_without_api_key(monkeypatch):
    """No OPENAI_API_KEY means no API call and untouched listings."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    scored = _make_scored()
    with respx.mock:
        route = respx.post(_OPENAI_URL).mock(return_value=_openai_response("x"))
        await analyse_top([scored], _make_profile())
    assert not route.called
    assert scored.analyst_md == ""  # field default — never populated


@pytest.mark.asyncio
async def test_analyse_top_api_error_leaves_empty_fields(monkeypatch):
    """An OpenAI failure degrades to empty analysis instead of raising."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    scored = _make_scored()
    with respx.mock:
        respx.post(_OPENAI_URL).mock(return_value=httpx.Response(500))
        await analyse_top([scored], _make_profile())
    assert scored.analyst_md == ""
    assert scored.summary_md == ""
