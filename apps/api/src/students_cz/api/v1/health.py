"""Liveness, and the two things that fail independently of it.

Its own router with no prefix: `/healthz` is not part of the versioned API and
must not move when the API version does.
"""

import asyncio
import logging
import time as clock
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, FastAPI, Request
from sqlalchemy import select

from students_cz.api.deps import SessionDep
from students_cz.core.config import get_settings

log = logging.getLogger("students_cz")

_STARTED_AT = datetime.now(UTC)

# The container healthcheck hits this every few seconds and the shared edge
# adds its own. Long enough that Telegram is asked about once a minute, short
# enough that a deployment watching this sees a webhook disappear.
WEBHOOK_CHECK_TTL = 60.0

# A failure is remembered too, but briefly: without this, an hour of Telegram
# being unreachable is an hour of every probe waiting on it.
WEBHOOK_FAILURE_TTL = 10.0

# Well under the container healthcheck's own budget. aiogram's default session
# waits 60 seconds, which is longer than anything watching this endpoint is
# willing to wait — a Telegram that hangs rather than refuses would take the
# API out of rotation, which is exactly what reporting this softly is meant to
# avoid.
WEBHOOK_CHECK_TIMEOUT = 2.5

health_router = APIRouter(tags=["ops"])


@health_router.get("/healthz")
async def healthz(request: Request, session: SessionDep) -> dict[str, str | int]:
    """Liveness plus the two things that fail independently.

    A webhook that never registered — or registered and was then cleared —
    leaves the catalog perfectly usable and the bot deaf, which is exactly the
    kind of half-failure nobody notices. It is reported here rather than folded
    into the status, because taking the whole service out of rotation over it
    would be worse.
    """
    await session.execute(select(1))
    uptime = datetime.now(UTC) - _STARTED_AT
    return {
        "status": "ok",
        "database": "ok",
        "webhook": await webhook_state(request.app),
        "uptime_seconds": int(uptime / timedelta(seconds=1)),
    }


def name_webhook_state(
    observed: str, *, expected: str, registration_error: str | None
) -> str:
    """The one place a webhook URL becomes an answer somebody reads.

    Named here rather than wherever the observation was made: the endpoint and
    the watch in `main.py` both make it, and two copies of this vocabulary
    drift — one of them quietly losing the registration error, which is the
    only thing that says *why* the bot is deaf.
    """
    if observed == expected:
        return "ok"
    if observed:
        return f"elsewhere: {observed}"
    # "Missing" says the bot is deaf; the registration attempt's own error, if
    # there was one, says why.
    why = f" (registration failed: {registration_error})" if registration_error else ""
    return f"missing: Telegram has no webhook for this bot{why}"


async def webhook_state(app: FastAPI) -> str:
    """Where Telegram says it is sending updates, not where we asked it to.

    The application remembering a past success is not evidence of one. A
    webhook registers, something clears it afterwards, and the remembered
    answer stays "ok" for as long as the process lives — so the one dial that
    exists to catch a deaf bot reports green while the bot is deaf.

    Asked at most once per `WEBHOOK_CHECK_TTL`, under a lock so a burst of
    probes makes one call rather than a burst of calls, on a timeout far
    shorter than anything watching this endpoint will wait, and never fatal:
    Telegram having a bad minute is not a reason to fail a health check that
    the edge uses to decide whether the catalog is up.
    """
    bot = getattr(app.state, "bot", None)
    if bot is None:
        return "not configured"

    fresh = _cached(app)
    if fresh is not None:
        return fresh

    async with _lock_for(app):
        # Somebody else may have answered it while this one waited.
        fresh = _cached(app)
        if fresh is not None:
            return fresh
        return await _ask_telegram(app, bot)


def _lock_for(app: FastAPI) -> asyncio.Lock:
    """Kept beside the cache it guards, not at module level.

    An `asyncio.Lock` binds to the first event loop that contends it and
    refuses every later one, and the acquire sits outside the try below — so a
    module-level lock would eventually raise straight out of a health check
    that promises never to be fatal.
    """
    lock = getattr(app.state, "webhook_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app.state.webhook_lock = lock
    return lock


def _cached(app: FastAPI) -> str | None:
    """The last answer, while it is still worth trusting.

    A failure is held for a fraction of the time a real answer is: an outage
    must not pin the reading for a full minute, and a success is not worth
    asking about again that often.
    """
    cached = getattr(app.state, "webhook_observed", None)
    if cached is None:
        return None
    ttl = (
        WEBHOOK_FAILURE_TTL
        if getattr(app.state, "webhook_observed_failed", False)
        else WEBHOOK_CHECK_TTL
    )
    checked_at = getattr(app.state, "webhook_checked_at", 0.0)
    return cached if clock.monotonic() - checked_at < ttl else None


async def _ask_telegram(app: FastAPI, bot) -> str:
    expected = get_settings().webhook_url
    failed = False
    # Noted before the call, not after: the watch in `main.py` may heal the
    # webhook while this one is still waiting on Telegram, and an older answer
    # must not overwrite a newer one — least of all by replacing "ok" with the
    # "missing" it was sent to check.
    started = clock.monotonic()
    try:
        info = await asyncio.wait_for(
            bot.get_webhook_info(), timeout=WEBHOOK_CHECK_TIMEOUT
        )
    except Exception as exc:
        # `str()` of a bare TimeoutError is empty, and an exception object is
        # always truthy — so the reason has to be chosen on the text, not on
        # the exception. Without this the timeout path reports "unknown: " and
        # logs a line with no cause, which is the opposite of the point.
        reason = str(exc) or type(exc).__name__
        log.warning("could not read the webhook from Telegram: %s", reason)
        state = f"unknown: {reason}"
        failed = True
    else:
        observed = str(getattr(info, "url", "") or "")
        state = name_webhook_state(
            observed,
            expected=expected,
            registration_error=getattr(app.state, "webhook_error", None),
        )
        if observed and observed != expected:
            log.error("Telegram points at %s, expected %s", observed, expected)
        elif not observed:
            log.error("Telegram has no webhook; expected %s", expected)

    if getattr(app.state, "webhook_checked_at", 0.0) <= started:
        app.state.webhook_observed = state
        app.state.webhook_observed_failed = failed
        app.state.webhook_checked_at = clock.monotonic()
    return state
