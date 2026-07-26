"""Reaching someone whose app is closed.

Every notification here answers something the recipient started — they posted a
request, or they answered one — so this is not the announcement channel and
deliberately does not consult `unsubscribed_at`: /stop opts out of us writing
unprompted, not out of being told that the thing you asked for happened.

Nothing in here may raise. A notification is a side effect of an action that has
already been committed; if Telegram is down, the response was still recorded and
the person will see it in the app.
"""

import asyncio
import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    WebAppInfo,
)

from konnekt.bot.texts import OPEN_APP, pick
from konnekt.db.models.enums import UiLang
from konnekt.db.session import get_sessionmaker
from konnekt.services.people import mark_unreachable

log = logging.getLogger("konnekt.notify")

# Telegram occasionally takes seconds to answer. The caller is a background
# task, but an unbounded wait still leaks a task per stuck send.
SEND_TIMEOUT = 10.0


def _keyboard(lang: UiLang, app_url: str | None) -> InlineKeyboardMarkup | None:
    """A button that opens the mini app, when we know our own address.

    A web_app button requires an https URL; during local development there is
    none, and a notification without a button is better than a failed send.
    """
    if not app_url or not app_url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=pick(OPEN_APP, lang),
                    web_app=WebAppInfo(url=app_url),
                )
            ]
        ]
    )


async def tell(
    bot: Bot | None,
    *,
    tg_id: int,
    text: str,
    lang: UiLang,
    app_url: str | None = None,
) -> bool:
    """Send one message. Returns whether it arrived.

    `bot` is None when the API runs without a token, which is how it runs
    locally — so every caller works unchanged with notifications simply not
    happening.
    """
    if bot is None:
        log.debug("no bot configured; not notifying %s", tg_id)
        return False

    try:
        await asyncio.wait_for(
            bot.send_message(
                chat_id=tg_id,
                text=text,
                reply_markup=_keyboard(lang, app_url),
                # These are short and self-contained; a link preview would be
                # the only thing in the message with a picture. The options
                # object rather than disable_web_page_preview, which aiogram
                # keeps only as a deprecated alias.
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
            timeout=SEND_TIMEOUT,
        )
    except TelegramForbiddenError as exc:
        # Blocked, or never started the bot. An answer, not a failure: recorded
        # so nothing tries again and finds out the same way.
        async with get_sessionmaker()() as session:
            await mark_unreachable(session, tg_id, str(exc))
            await session.commit()
        return False
    except TelegramRetryAfter as exc:
        # Not retried here. This is a single message to a single person, and
        # holding a background task open for the flood-wait window to deliver
        # something the app already shows is not worth it.
        log.warning("flood wait %ss notifying %s", exc.retry_after, tg_id)
        return False
    except Exception as exc:
        # Includes the timeout above: asyncio.TimeoutError is TimeoutError is
        # an Exception. Everything here is "the message did not arrive", and
        # none of it is worth failing the caller over.
        log.warning("could not notify %s: %s", tg_id, exc)
        return False
    return True


def quote(value: str, limit: int = 300) -> str:
    """Prepare user-written text for an HTML message.

    Escaped, because the bot sends HTML and someone's request may legitimately
    contain "<3" or an ampersand; truncated, because a notification is a
    summary and Telegram rejects a message over 4096 characters outright.
    """
    collapsed = " ".join(value.split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1].rstrip() + "…"
    return escape(collapsed)
