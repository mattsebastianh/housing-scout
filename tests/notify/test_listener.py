"""Tests for the Telegram /scout on-demand listener."""

import json
import re
import sys

import httpx
import pytest
import respx

from scout.core import runlock
from scout.core.notify.listener import (
    build_run_args,
    get_updates,
    handle_update,
    parse_scout_command,
    read_offset,
    write_offset,
)

KNOWN = ["barcelona", "valencia", "girona"]


# --- command parsing -------------------------------------------------------

def test_parse_bare_scout_selects_all_cities():
    """A bare /scout runs every configured city."""
    cmd = parse_scout_command("/scout", KNOWN)
    assert cmd.cities == KNOWN
    assert cmd.unknown == []


def test_parse_single_city():
    """/scout valencia narrows the run to that city."""
    cmd = parse_scout_command("/scout valencia", KNOWN)
    assert cmd.cities == ["valencia"]


def test_parse_multiple_cities_space_separated():
    """Several space-separated cities select that subset, in the given order."""
    cmd = parse_scout_command("/scout valencia girona", KNOWN)
    assert cmd.cities == ["valencia", "girona"]


@pytest.mark.parametrize("text", ["/scout valencia, girona", "/scout valencia,girona"])
def test_parse_comma_separated(text):
    """Commas (with or without spaces) also separate city tokens."""
    cmd = parse_scout_command(text, KNOWN)
    assert cmd.cities == ["valencia", "girona"]


def test_parse_case_and_accent_insensitive():
    """Matching tolerates capitals and accents: València → valencia."""
    cmd = parse_scout_command("/Scout VALÈNCIA Girona", KNOWN)
    assert cmd.cities == ["valencia", "girona"]


def test_parse_botname_suffix():
    """Telegram's /scout@BotName group form is recognised."""
    cmd = parse_scout_command("/scout@ChaletSpainBot barcelona", KNOWN)
    assert cmd.cities == ["barcelona"]


def test_parse_unknown_city_reported():
    """Unmatched tokens land in .unknown; matched ones still resolve."""
    cmd = parse_scout_command("/scout madrid girona", KNOWN)
    assert cmd.cities == ["girona"]
    assert cmd.unknown == ["madrid"]


def test_parse_duplicate_city_deduplicated():
    """Repeating a city does not queue it twice."""
    cmd = parse_scout_command("/scout valencia valencia", KNOWN)
    assert cmd.cities == ["valencia"]


@pytest.mark.parametrize("text", [None, "", "hola", "scout valencia", "/start"])
def test_parse_non_scout_returns_none(text):
    """Anything that is not a /scout command parses to None."""
    assert parse_scout_command(text, KNOWN) is None


# --- offset persistence ----------------------------------------------------

def test_offset_missing_file_reads_zero(tmp_path):
    """No state file yet means offset 0 (process everything Telegram holds)."""
    assert read_offset(tmp_path / "offset") == 0


def test_offset_roundtrip(tmp_path):
    """Written offsets read back unchanged."""
    path = tmp_path / "offset"
    write_offset(path, 123456)
    assert read_offset(path) == 123456


# --- dispatch args ---------------------------------------------------------

def test_build_run_args_city_flags(tmp_path):
    """The pipeline subprocess gets one --city flag per requested city."""
    args = build_run_args(["valencia", "girona"], tmp_path)
    assert args[0] == sys.executable
    assert args[1].endswith("run_daily.py")
    assert args[2:] == ["--city", "valencia", "--city", "girona"]


# --- update handling -------------------------------------------------------

def _update(text, chat_id=42, update_id=1):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


def _mock_send():
    return respx.post(re.compile(r".*/sendMessage")).mock(
        return_value=httpx.Response(200, json={"ok": True})
    )


class _StubChat:
    """Chat-agent stand-in recording what it was asked."""

    def __init__(self, answer="respuesta ia"):
        self.answer = answer
        self.seen = []

    async def reply(self, text, client, *, context=None):
        self.seen.append((text, context))
        return self.answer


async def _handle(update, tmp_path, dispatched, lock_path=None, chat=None):
    async def dispatch(cities):
        dispatched.append(cities)

    async with httpx.AsyncClient() as client:
        await handle_update(
            update,
            client=client,
            token="tok",
            chat_id="42",
            known_cities=KNOWN,
            lock_path=lock_path or tmp_path / "run.lock",
            dispatch=dispatch,
            chat=chat,
        )


@pytest.mark.asyncio
async def test_message_from_other_chat_ignored(tmp_path):
    """A /scout from any chat but the authorised one is silently dropped."""
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("/scout", chat_id=999), tmp_path, dispatched)
    assert not route.called
    assert dispatched == []


@pytest.mark.asyncio
async def test_scout_acks_and_dispatches_all_cities(tmp_path):
    """Bare /scout acknowledges and dispatches every configured city."""
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("/scout"), tmp_path, dispatched)
    assert dispatched == [KNOWN]
    ack = json.loads(route.calls[0].request.content)["text"]
    assert "Barcelona, Valencia, Girona" in ack


@pytest.mark.asyncio
async def test_scout_subset_dispatches_only_those(tmp_path):
    """/scout with cities dispatches exactly that subset."""
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("/scout valencia girona"), tmp_path, dispatched)
    assert dispatched == [["valencia", "girona"]]
    ack = json.loads(route.calls[0].request.content)["text"]
    assert "Valencia, Girona" in ack


@pytest.mark.asyncio
async def test_unknown_city_replies_help_without_dispatch(tmp_path):
    """An unknown city gets the valid-cities reply and runs nothing."""
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("/scout madrid"), tmp_path, dispatched)
    assert dispatched == []
    reply = json.loads(route.calls[0].request.content)["text"]
    assert "madrid" in reply
    assert "barcelona" in reply and "valencia" in reply and "girona" in reply


@pytest.mark.asyncio
async def test_busy_lock_replies_without_dispatch(tmp_path):
    """While a run holds the lock, /scout answers busy instead of double-running."""
    lock = tmp_path / "run.lock"
    runlock.acquire(lock)  # our own live pid holds it
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("/scout"), tmp_path, dispatched, lock_path=lock)
    assert dispatched == []
    reply = json.loads(route.calls[0].request.content)["text"]
    assert "en curso" in reply


@pytest.mark.asyncio
async def test_plain_chatter_ignored_without_chat_agent(tmp_path):
    """With no chat agent wired in, non-command messages stay silent."""
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("hola bot"), tmp_path, dispatched)
    assert not route.called
    assert dispatched == []


@pytest.mark.asyncio
async def test_plain_chatter_gets_chat_agent_reply(tmp_path):
    """Non-command text is answered by the chat agent, never dispatched."""
    chat = _StubChat(answer="¡Hola! Usa /scout cuando quieras buscar.")
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("hola bot"), tmp_path, dispatched, chat=chat)
    assert dispatched == []
    assert chat.seen == [("hola bot", None)]
    reply = json.loads(route.calls[0].request.content)["text"]
    assert "¡Hola!" in reply


@pytest.mark.asyncio
async def test_chat_agent_not_consulted_for_commands(tmp_path):
    """/scout goes to dispatch; the chat agent never sees command traffic."""
    chat = _StubChat()
    dispatched = []
    with respx.mock:
        _mock_send()
        await _handle(_update("/scout valencia"), tmp_path, dispatched, chat=chat)
    assert dispatched == [["valencia"]]
    assert chat.seen == []


@pytest.mark.asyncio
async def test_chat_agent_ignores_unauthorised_chats(tmp_path):
    """Auth still comes first: strangers get no AI conversation either."""
    chat = _StubChat()
    dispatched = []
    with respx.mock:
        route = _mock_send()
        await _handle(_update("hola", chat_id=999), tmp_path, dispatched, chat=chat)
    assert not route.called
    assert chat.seen == []


@pytest.mark.asyncio
async def test_chat_agent_told_when_run_in_progress(tmp_path):
    """While the lock is held, the agent gets a run-in-progress context note."""
    lock = tmp_path / "run.lock"
    runlock.acquire(lock)
    chat = _StubChat()
    dispatched = []
    with respx.mock:
        _mock_send()
        await _handle(_update("¿cómo va?"), tmp_path, dispatched, lock_path=lock, chat=chat)
    (text, context), = chat.seen
    assert text == "¿cómo va?"
    assert "búsqueda en curso" in context


# --- long-poll fetch -------------------------------------------------------

@pytest.mark.asyncio
async def test_get_updates_passes_offset_and_returns_result():
    """getUpdates is called with the offset and its result array is returned."""
    with respx.mock:
        route = respx.get(re.compile(r".*/getUpdates")).mock(
            return_value=httpx.Response(200, json={"ok": True, "result": [{"update_id": 7}]})
        )
        async with httpx.AsyncClient() as client:
            result = await get_updates(client, "tok", offset=5, timeout=0)
    assert result == [{"update_id": 7}]
    assert route.calls[0].request.url.params["offset"] == "5"
