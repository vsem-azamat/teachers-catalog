"""The one route that does not need a Telegram account.

Someone who opens the domain in a browser has no init data, nothing to sign a
request with, and no chat to be answered in. What they get is a redirect into
the bot, derived from the bot's own token so the handle is never hardcoded.
"""

import logging
import time as clock

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

log = logging.getLogger("students_cz")

router = APIRouter()


BOT_LOOKUP_COOLDOWN = 30.0


async def _bot_username(app) -> str | None:
    """The bot's public handle, asked for once and remembered."""
    cached = getattr(app.state, "bot_username", None)
    if cached:
        return cached
    bot = getattr(app.state, "bot", None)
    if bot is None:
        return None
    quiet_until = getattr(app.state, "bot_lookup_quiet_until", 0.0)
    now = clock.monotonic()
    if now < quiet_until:
        return None
    try:
        me = await bot.get_me()
    except Exception:
        app.state.bot_lookup_quiet_until = now + BOT_LOOKUP_COOLDOWN
        log.warning("could not read the bot's own username", exc_info=True)
        return None
    app.state.bot_username = me.username
    return me.username


@router.get("/open", include_in_schema=False, tags=["public"])
async def open_in_telegram(request: Request) -> RedirectResponse:
    """Send a browser to the bot.

    Unauthenticated on purpose: this is what the landing page's button points
    at, and the landing is what someone sees who has never opened Telegram
    here. It redirects rather than returning the handle so the handle exists
    in exactly one place — the token the API is already running with. Change
    the bot and nothing in the frontend or the build needs to know.
    """
    username = await _bot_username(request.app)
    if username is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no bot is configured")
    # 302 rather than 301: a permanent redirect would be cached by the browser
    # for ever, and the target is a handle that can change.
    return RedirectResponse(f"https://t.me/{username}", status_code=302)
