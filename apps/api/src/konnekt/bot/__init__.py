"""The bot half of the process.

Deliberately thin. Everything a student does happens in the mini app; the bot
exists to open it, to be the address people share, and to deliver notifications
later. Adding conversational flows here would recreate the command-driven
interface this rewrite exists to remove.
"""

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

from konnekt.bot.middleware import RememberUserMiddleware
from konnekt.core.config import Settings
from konnekt.db.session import get_sessionmaker
from konnekt.services.people import unsubscribe

router = Router(name="konnekt")

# Named rather than written inline, because these are claims about the code and
# a claim wants somewhere a test can read it. See tests/test_bot.py: one says
# what the catalog has, the other is careful not to offer a way back that does
# not exist.
GREETING = (
    "<b>Students CZ</b> — кто поможет с учёбой в Чехии.\n\n"
    "Репетиторы, подготовка к přijímačky, помощь на экзамене, "
    "нострификация и работы."
)

UNSUBSCRIBED = (
    "Больше писать не буду. Каталогом можно пользоваться как обычно — "
    "кнопка «Каталог» внизу."
)


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
            "Students CZ is still being set up — the mini app has no public address yet."
        )
        return

    # No mention of announcements or of /stop. The greeting is the first thing
    # a new person reads, and every sentence in it that is not about what the
    # catalog does is a sentence spent talking about ourselves.
    await message.answer(
        GREETING,
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
        if await unsubscribe(session, message.from_user.id):
            await session.commit()

    await message.answer(UNSUBSCRIBED)
