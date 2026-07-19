"""Tests for Telegram notification message building."""

import re
from collections import Counter
from datetime import datetime, UTC

import httpx
import pytest
import respx

from scout.core.models import Listing, ScoredListing
from scout.core.notify.telegram import (
    _build_failure_message,
    _build_property_message,
    _build_success_message,
    notify_success,
)


def _make_listing(price=230_000, size=140, municipality="Abrera", portal="fotocasa"):
    return Listing(
        portal=portal,
        external_id="test-1",
        city="barcelona",
        url="https://fotocasa.es/test",
        price_eur=price,
        size_m2=size,
        bedrooms=3,
        bathrooms=2,
        municipality=municipality,
        province="Barcelona",
        address=None,
        lat=41.5,
        lon=1.9,
        description="Casa con jardín y piscina.",
        days_on_market=20,
        cadastral_ref=None,
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )


def _make_scored(price=230_000, composite=7.5):
    l = _make_listing(price=price)
    return ScoredListing(
        listing=l,
        dim_scores={"price": 7.0, "location": 8.0},
        composite=composite,
        positives_md="- Precio competitivo",
        risks_md="- ⚠ Verificar catastro",
    )


def test_success_message_no_listings():
    """Zero-listings run produces a message with run stats and no property cards."""
    msg = _build_success_message(
        app_name="Housing Scout",
        run_id=42,
        fetched=30,
        excluded=Counter({"OUT_OF_PRICE_RANGE": 30}),
        new_total=0,
        reported_total=0,
        top=[],
        price_min=150_000,
        price_max=250_000,
        cities_label="Barcelona y Valencia",
    )
    assert "Run #42" in msg
    assert "30" in msg
    assert "Sin propiedades nuevas" in msg
    assert "150" in msg
    assert "250" in msg
    # header carries the configured app name, not hardcoded branding
    assert "Housing Scout — Informe" in msg
    assert "Chalet" not in msg
    assert "Diario" not in msg


def test_success_message_header_uses_custom_app_name():
    """A custom report.app_name flows into the success header (HTML-escaped)."""
    msg = _build_success_message(
        app_name="Maison & Co",
        run_id=1,
        fetched=0,
        excluded=Counter(),
        new_total=0,
        reported_total=0,
        top=[],
        price_min=100_000,
        price_max=200_000,
        cities_label="Lyon",
    )
    assert "Maison &amp; Co — Informe" in msg


def test_success_message_announces_property_cards():
    """Header message carries run stats and points at the per-property cards."""
    scored = [_make_scored(230_000, 7.5), _make_scored(245_000, 6.8)]
    msg = _build_success_message(
        app_name="Housing Scout",
        run_id=1,
        fetched=50,
        excluded=Counter({"OUT_OF_PRICE_RANGE": 48}),
        new_total=2,
        reported_total=2,
        top=scored,
        price_min=150_000,
        price_max=250_000,
        cities_label="Barcelona",
    )
    assert "Top 2 propiedades" in msg
    # property details now live in their own per-property messages
    assert "Abrera" not in msg


def test_property_message_card_and_button():
    """Per-property card shows the key facts; the link is an inline URL button."""
    msg, keyboard = _build_property_message(1, _make_scored(230_000, 7.5))
    assert "1. Abrera, Barcelona" in msg
    assert "230.000" in msg
    assert "7.5/10" in msg
    button = keyboard["inline_keyboard"][0][0]
    assert button["url"] == "https://fotocasa.es/test"
    assert "Fotocasa" in button["text"]


def test_property_message_includes_plot_when_known():
    """Plot size appears on the card only when the listing carries one."""
    scored = _make_scored()
    scored.listing.plot_m2 = 1_591
    msg, _ = _build_property_message(2, scored)
    assert "Parcela: 1.591 m²" in msg
    msg_no_plot, _ = _build_property_message(2, _make_scored())
    assert "Parcela" not in msg_no_plot


@pytest.mark.asyncio
async def test_notify_success_sends_header_plus_capped_property_cards(monkeypatch):
    """notify_success posts one header message plus at most 5 property cards."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    scored = [_make_scored() for _ in range(10)]

    with respx.mock:
        route = respx.post(re.compile(r".*/sendMessage")).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await notify_success(
            app_name="Housing Scout",
            run_id=1,
            fetched=50,
            excluded=Counter(),
            new_total=10,
            reported_total=10,
            top=scored,
            price_min=150_000,
            price_max=250_000,
            cities_label="Barcelona",
        )

    assert route.call_count == 6  # 1 header + 5 capped property cards
    import json as _json
    card_payload = _json.loads(route.calls[1].request.content)
    assert card_payload["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://fotocasa.es/test"


def test_failure_message():
    """Failure message includes the app name, run ID and the error text."""
    msg = _build_failure_message(app_name="Housing Scout", run_id=7, error="Connection refused")
    assert "Run #7" in msg
    assert "Connection refused" in msg
    assert "Error" in msg
    assert "Housing Scout" in msg
    assert "Chalet" not in msg
    assert "diario" not in msg


def test_html_special_chars_escaped():
    """HTML special characters are entity-escaped in both message builders."""
    scored = _make_scored()
    scored.listing.municipality = "Sant <Quirze>"
    msg = _build_success_message(
        app_name="Housing Scout",
        run_id=1,
        fetched=1,
        excluded=Counter(),
        new_total=1,
        reported_total=1,
        top=[scored],
        price_min=150_000,
        price_max=250_000,
        cities_label="Barcelona & Valencia",
    )
    assert "Barcelona &amp; Valencia" in msg
    card, _ = _build_property_message(1, scored)
    assert "&lt;Quirze&gt;" in card
    assert "<Quirze>" not in card


@pytest.mark.asyncio
async def test_send_document_posts_file_to_telegram(tmp_path):
    """Sends the report file as a multipart document to the Telegram sendDocument endpoint."""
    report = tmp_path / "2026-05-28.md"
    report.write_text("# Daily Report", encoding="utf-8")

    token = "tok123"
    chat_id = "42"
    endpoint = f"https://api.telegram.org/bot{token}/sendDocument"

    with respx.mock:
        route = respx.post(endpoint).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient() as client:
            from scout.core.notify.telegram import _send_document
            await _send_document(client, token, chat_id, report)

        assert route.called
        content = route.calls[0].request.content
        assert b"2026-05-28.md" in content
        assert b"Daily Report" in content


@pytest.mark.asyncio
async def test_send_document_does_not_raise_on_http_error(tmp_path):
    """A 400 response from Telegram is absorbed without raising an exception."""
    report = tmp_path / "report.md"
    report.write_text("content", encoding="utf-8")

    with respx.mock:
        respx.post(re.compile(r".*/sendDocument")).mock(
            return_value=httpx.Response(400, json={"ok": False, "description": "Bad Request"})
        )
        async with httpx.AsyncClient() as client:
            from scout.core.notify.telegram import _send_document
            await _send_document(client, "tok", "42", report)
        # no exception raised — soft failure
