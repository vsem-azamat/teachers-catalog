"""The bot half of the process.

Deliberately thin. Everything a student does happens in the mini app; the bot
exists to open it, to be the address people share, and to deliver notifications
later. Adding conversational flows here would recreate the command-driven
interface this rewrite exists to remove.
"""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from sqlalchemy import select

from konnekt.bot.middleware import RememberUserMiddleware
from konnekt.core.config import Settings
from konnekt.db.models import User
from konnekt.db.session import get_sessionmaker

router = Router(name="konnekt")


def build_bot(settings: Settings) -> Bot:
    return Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher()
    # Outer, not inner: it has to run for every update including the ones no
    # handler matches, because someone who sends something we do not
    # understand is still someone who exists.
    dispatcher.update.outer_middleware(RememberUserMiddleware(settings))
    dispatcher.include_router(router)
    return dispatcher


@router.message(CommandStart())
async def on_start(message: Message, settings: Settings) -> None:
    app_url = settings.public_base_url or ""
    if not app_url:
        await message.answer(
            "Konnekt is still being set up — the mini app has no public address yet."
        )
        return

    await message.answer(
        "<b>Konnekt</b> — кто поможет с учёбой в Чехии.\n\n"
        "Репетиторы, подготовка к přijímačky, помощь на экзамене, "
        "нострификация, работы и материалы.\n\n"
        "Иногда буду писать, если появится что-то по твоей теме. "
        "Надоест — /stop.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Открыть каталог",
                        web_app=WebAppInfo(url=app_url),
                    )
                ]
            ]
        ),
    )


async def configure(bot: Bot, settings: Settings) -> None:
    """Point the persistent menu button at the mini app.

    This is what makes the app reachable without anyone typing a command —
    the whole point of moving off a command-driven interface.
    """
    if not settings.public_base_url:
        return
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Каталог",
            web_app=WebAppInfo(url=settings.public_base_url),
        )
    )


@router.message(Command("stop"))
async def on_stop(message: Message) -> None:
    """Opt out of announcements.

    Offered because the alternative is that the only way to stop hearing from
    us is to block the bot — which loses the person entirely, and tells us
    nothing about why.
    """
    if message.from_user is None:
        return

    async with get_sessionmaker()() as session:
        user = await session.scalar(
            select(User).where(User.tg_id == message.from_user.id)
        )
        if user is not None and user.unsubscribed_at is None:
            user.unsubscribed_at = datetime.now(UTC)
            await session.commit()

    await message.answer(
        "Больше писать не буду. Каталогом можно пользоваться как обычно — "
        "кнопка «Каталог» внизу. Передумаешь — /start."
    )
