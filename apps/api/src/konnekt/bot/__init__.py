"""The bot half of the process.

Deliberately thin. Everything a student does happens in the mini app; the bot
exists to open it, to be the address people share, and to deliver notifications
later. Adding conversational flows here would recreate the command-driven
interface this rewrite exists to remove.
"""

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from konnekt.core.config import Settings

router = Router(name="konnekt")


def build_bot(settings: Settings) -> Bot:
    return Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
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
        "нострификация, работы и материалы.",
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
