"""Record everyone who touches the bot, on every update.

Not only on /start. Someone who presses a button, forwards a message or comes
back a month later is equally reachable, and equally worth knowing about. The
middleware runs before any handler, so a handler that fails still leaves the
person recorded — which is the point, since the reason to record them has
nothing to do with whether the reply worked.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TelegramUser

from students_cz.core.config import Settings
from students_cz.db.models.enums import UserEventKind
from students_cz.db.session import get_sessionmaker
from students_cz.services.people import log_event, remember

log = logging.getLogger("students_cz.bot")


def _started_with(update: Update) -> tuple[bool, str | None]:
    """Is this /start, and what deep link brought them?

    `t.me/bot?start=instagram` arrives as the text "/start instagram". The
    payload is how a campaign is told apart from a share, and it is only ever
    present on this one command.
    """
    message = update.message
    if message is None or not message.text:
        return False, None
    parts = message.text.split(maxsplit=1)
    if parts[0].split("@", 1)[0] != "/start":
        return False, None
    return True, parts[1].strip() if len(parts) > 1 else None


class RememberUserMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, sessionmaker=None) -> None:
        self.settings = settings
        # Injectable so a test can hand it a session it controls. Resolved
        # lazily otherwise, because the engine must not be created at import.
        self._sessionmaker = sessionmaker

    def _session(self):
        return (self._sessionmaker or get_sessionmaker())()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")
        # Channel posts and similar have no author; there is nobody to record.
        if telegram_user is None or telegram_user.is_bot:
            return await handler(event, data)

        update = data.get("event_update")
        is_start, start_param = (
            _started_with(update) if isinstance(update, Update) else (False, None)
        )

        try:
            # Its own session, committed immediately: the handler may take a
            # while or throw, and neither should decide whether we remember
            # that this person exists.
            async with self._session() as session:
                user = await remember(
                    session,
                    tg_id=telegram_user.id,
                    first_name=telegram_user.first_name,
                    last_name=telegram_user.last_name,
                    username=telegram_user.username,
                    language_code=telegram_user.language_code,
                    is_premium=bool(telegram_user.is_premium),
                    supported_langs=self.settings.supported_ui_langs,
                    source=start_param,
                    started_bot=is_start,
                )
                await log_event(
                    session,
                    user.id,
                    UserEventKind.BOT_START if is_start else UserEventKind.BOT_MESSAGE,
                    source=start_param,
                )
                await session.commit()
                data["students_cz_user_id"] = user.id
        except Exception:
            # A database that is briefly unavailable should cost us the record,
            # not the reply. The person still gets an answer.
            log.exception("could not record telegram user %s", telegram_user.id)

        return await handler(event, data)
