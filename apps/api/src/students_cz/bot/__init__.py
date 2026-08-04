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
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from students_cz.bot.middleware import RememberUserMiddleware
from students_cz.core.config import Settings
from students_cz.db.session import get_sessionmaker
from students_cz.services.people import unsubscribe

router = Router(name="students_cz")

# Named rather than written inline, because these are claims about the code and
# a claim wants somewhere a test can read it. See tests/test_bot.py: one says
# what the catalog has, the other is careful not to offer a way back that does
# not exist.
GREETING = (
    "<b>Students CZ</b> — кто поможет с учёбой в Чехии.\n\n"
    "Репетиторы, подготовка к přijímačky, помощь на экзамене, "
    "нострификация и работы."
)

# "Больше писать не буду" was the first half of this sentence and it was not
# true either. `notify.Recipient.of` does not consult `unsubscribed_at` on
# purpose — an answer to your own request is not us writing to you unprompted —
# so those messages keep arriving, and somebody told otherwise finds out when
# one does.
UNSUBSCRIBED = (
    "Рассылок не будет. Ответы на твои заявки продолжат приходить — "
    "их ты просил сам. Каталог работает как обычно."
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


# The two that exist. Telegram keeps whatever list it was last given, and this
# token answered to a command-driven bot before this one — so a bot that sets
# none is still offering `/language`, which nothing here handles. Two of them,
# and both are ways out rather than ways around the app.
COMMANDS = [
    BotCommand(command="start", description="Открыть каталог"),
    # Not "не писать мне", which is the promise `UNSUBSCRIBED` below exists to
    # take back: answers to your own requests keep arriving, because you asked
    # for them. The line before the command has to say the same as the line
    # after it.
    BotCommand(command="stop", description="Не присылать рассылки"),
]

# What a message gets when it is not one of those. Short on purpose: the reply
# exists to carry `ReplyKeyboardRemove`, and the menu button beside the field
# is where the app actually is.
NOT_A_CONVERSATION = (
    "Всё происходит в приложении — открой его кнопкой рядом с полем ввода."
)


async def configure(bot: Bot, settings: Settings) -> None:
    """Say what this bot offers, in the two places Telegram remembers it.

    The menu button is what makes the app reachable without anyone typing a
    command — the whole point of moving off a command-driven interface. The
    command list is the other half, and it is set here rather than left alone
    because "left alone" means the previous bot's list.
    """
    # The default scope, which is where the previous bot's list is: measured on
    # 2026-08-04 against production, every narrower scope and every language
    # variant is empty, and Telegram falls back to this one.
    await bot.set_my_commands(COMMANDS)
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

    # Carries the removal too: somebody typing /stop is as likely to have the
    # old keyboard in front of them as anybody else.
    await message.answer(UNSUBSCRIBED, reply_markup=ReplyKeyboardRemove())


@router.message()
async def on_anything_else(message: Message) -> None:
    """Anything that is not one of the two commands.

    Which, for anybody who used the bot this token belonged to, is most often
    a tap on a button still sitting in their chat: Telegram keeps a reply
    keyboard until a message removes it, and those send their own label as
    ordinary text. The reply is one line and its job is the removal.

    Nothing is said to an update with no sender — a channel post — for the
    same reason `on_stop` returns: there is nobody there to have asked.
    """
    if message.from_user is None:
        return
    await message.answer(NOT_A_CONVERSATION, reply_markup=ReplyKeyboardRemove())
