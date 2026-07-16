"""Telegram long-poll listener — on-demand scout runs via /scout messages.

Runs as its own process (``run_listener.py``) under launchd. It long-polls the
bot's ``getUpdates`` endpoint, and when the authorised chat sends ``/scout``
(optionally naming a subset of the configured cities) it launches the normal
pipeline as a ``run_daily.py`` subprocess. Everything downstream — scraping,
scoring, notification — is untouched: results arrive through the usual
Telegram cards. The weekly scheduled run is unaffected; the shared
``scout.core.runlock`` pidfile keeps the two from ever overlapping.
"""

import asyncio
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from scout.core import runlock
from scout.core.notify.telegram import _API, _escape, _post

log = structlog.get_logger("notify.listener")

_POLL_TIMEOUT_S = 50  # Telegram long-poll window
_RETRY_DELAY_S = 5


@dataclass
class ScoutCommand:
    """A parsed /scout request: resolved city names plus unmatched tokens."""

    cities: list[str]
    unknown: list[str]


def _normalise(token: str) -> str:
    decomposed = unicodedata.normalize("NFKD", token)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def parse_scout_command(text: str | None, known_cities: list[str]) -> ScoutCommand | None:
    """Parse a message into a ScoutCommand, or None when it isn't /scout.

    Bare ``/scout`` selects every configured city. Otherwise city tokens may
    be separated by spaces and/or commas and are matched case- and
    accent-insensitively against the configured city names. The
    ``/scout@BotName`` form Telegram appends in groups is accepted too.
    """
    if not text:
        return None
    head, _, rest = text.strip().partition(" ")
    if head.split("@", 1)[0].casefold() != "/scout":
        return None
    tokens = [t for t in re.split(r"[\s,]+", rest) if t]
    if not tokens:
        return ScoutCommand(cities=list(known_cities), unknown=[])
    by_norm = {_normalise(name): name for name in known_cities}
    cities: list[str] = []
    unknown: list[str] = []
    for token in tokens:
        name = by_norm.get(_normalise(token))
        if name is None:
            unknown.append(token)
        elif name not in cities:
            cities.append(name)
    return ScoutCommand(cities=cities, unknown=unknown)


def read_offset(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return 0


def write_offset(path: Path, update_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(update_id))


def build_run_args(cities: list[str], project_root: Path) -> list[str]:
    """Command line for the pipeline subprocess: one --city flag per city."""
    args = [sys.executable, str(project_root / "run_daily.py")]
    for city in cities:
        args += ["--city", city]
    return args


async def get_updates(
    client: httpx.AsyncClient, token: str, *, offset: int, timeout: int = _POLL_TIMEOUT_S
) -> list[dict]:
    url = _API.format(token=token, method="getUpdates")
    resp = await client.get(
        url,
        params={"offset": offset, "timeout": timeout, "allowed_updates": '["message"]'},
        timeout=timeout + 10,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


async def handle_update(
    update: dict,
    *,
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    known_cities: list[str],
    lock_path: Path,
    dispatch,
    chat=None,
) -> None:
    """Process one Telegram update; ``dispatch(cities)`` starts a pipeline run.

    Non-command text goes to the optional ``chat`` agent (ChatAgent) so the
    conversation never falls silent; without one, plain chatter is ignored.
    """
    message = update.get("message") or {}
    if str((message.get("chat") or {}).get("id")) != str(chat_id):
        return  # not the authorised chat — ignore silently
    text = message.get("text")
    cmd = parse_scout_command(text, known_cities)
    if cmd is None:
        if chat is not None and text:
            context = (
                "Ahora mismo hay una búsqueda en curso; los resultados llegarán "
                "a este chat al terminar."
                if runlock.is_locked(lock_path)
                else None
            )
            answer = await chat.reply(text, client, context=context)
            if answer:
                await _post(client, token, chat_id, _escape(answer))
        return
    if cmd.unknown:
        await _post(
            client, token, chat_id,
            f"🤔 No reconozco: <b>{_escape(', '.join(cmd.unknown))}</b>.\n"
            f"Ciudades válidas: {_escape(', '.join(known_cities))}.\n"
            "Usa /scout para todas o /scout &lt;ciudad ciudad…&gt;",
        )
        return
    if runlock.is_locked(lock_path):
        await _post(
            client, token, chat_id,
            "⏳ Ya hay una búsqueda en curso — te aviso cuando termine.",
        )
        return
    label = ", ".join(c.title() for c in cmd.cities)
    await _post(
        client, token, chat_id,
        f"🔍 Buscando nuevas propiedades en <b>{_escape(label)}</b>… "
        "Te aviso con los resultados.",
    )
    await dispatch(cmd.cities)


async def _run_pipeline(cities: list[str], project_root: Path) -> None:
    args = build_run_args(cities, project_root)
    log.info("listener.run.start", cities=cities)
    proc = await asyncio.create_subprocess_exec(*args, cwd=project_root)
    rc = await proc.wait()
    log.info("listener.run.finished", rc=rc, cities=cities)


async def listen_forever(
    *,
    token: str,
    chat_id: str,
    known_cities: list[str],
    project_root: Path,
    lock_path: Path,
    offset_path: Path,
    chat=None,
    poll_timeout: int = _POLL_TIMEOUT_S,
) -> None:
    """Poll getUpdates forever, dispatching /scout runs in the background.

    Runs launch as background tasks so the loop keeps answering (and can reply
    "búsqueda en curso") while a pipeline is working.
    """
    running: set[asyncio.Task] = set()

    async def dispatch(cities: list[str]) -> None:
        task = asyncio.create_task(_run_pipeline(cities, project_root))
        running.add(task)
        task.add_done_callback(running.discard)

    log.info("listener.started", cities=known_cities)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                updates = await get_updates(
                    client, token, offset=read_offset(offset_path) + 1, timeout=poll_timeout
                )
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("listener.poll.failed", error=type(exc).__name__)
                await asyncio.sleep(_RETRY_DELAY_S)
                continue
            for update in updates:
                try:
                    await handle_update(
                        update,
                        client=client,
                        token=token,
                        chat_id=chat_id,
                        known_cities=known_cities,
                        lock_path=lock_path,
                        dispatch=dispatch,
                        chat=chat,
                    )
                except Exception as exc:  # a bad update must not kill the loop
                    log.warning("listener.handle.failed", error=str(exc))
                update_id = update.get("update_id")
                if isinstance(update_id, int) and update_id > read_offset(offset_path):
                    write_offset(offset_path, update_id)
