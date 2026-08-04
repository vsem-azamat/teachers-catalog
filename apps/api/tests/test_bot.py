"""What the bot says, and what saying it costs somebody.

The copy is tested here because it is a claim about the code. A sentence
telling somebody how to undo something is a promise, and the only person who
finds out that it is empty is the one who tried it.
"""

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz import bot as students_cz_bot
from students_cz.bot import GREETING, UNSUBSCRIBED
from students_cz.db.models import HelperProfile, HelpRequest, RequestResponse, User
from students_cz.db.models.enums import UiLang
from students_cz.services.people import unsubscribe

pytestmark = pytest.mark.asyncio

# `/start`, `/stop` — anything that reads as "type this and something happens".
COMMAND = re.compile(r"(?:^|\s)/[a-z][a-z_]*")


async def test_the_opt_out_reply_offers_no_way_back() -> None:
    """Because there is none.

    Nothing clears `unsubscribed_at` — not `remember`, which leaves everything
    the person chose alone, and not any other line in the tree. A reply that
    named a command would be describing a feature that does not exist, and the
    only way to discover that is to unsubscribe and try it.
    """
    assert COMMAND.search(UNSUBSCRIBED) is None


async def test_the_greeting_names_only_what_the_catalog_has() -> None:
    """`home_sections` returns no things at all — the second element is `[]`
    and the comment above it says why. Listing materials in the first sentence
    a new person reads is an invitation to look for a section that is not
    there."""
    assert "материал" not in GREETING.lower()


async def _person(session: AsyncSession, tg_id: int = 91001) -> User:
    user = User(
        tg_id=tg_id,
        first_name="Азамат",
        last_name="Алмазбек уулу",
        tg_username="azamat",
        ui_lang=UiLang.RU,
        source="instagram",
        bot_started_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def test_unsubscribing_records_when(session: AsyncSession) -> None:
    user = await _person(session)

    assert await unsubscribe(session, user.tg_id) is True
    assert user.unsubscribed_at is not None


async def test_unsubscribing_twice_changes_nothing(session: AsyncSession) -> None:
    """Answers whether it did anything, so a caller can tell "you are now
    unsubscribed" apart from "you already were" without asking twice."""
    user = await _person(session)
    await unsubscribe(session, user.tg_id)
    first = user.unsubscribed_at

    assert await unsubscribe(session, user.tg_id) is False
    assert user.unsubscribed_at == first


async def test_unsubscribing_somebody_unknown_is_not_an_error(
    session: AsyncSession,
) -> None:
    """A /stop from someone with no row is a person the middleware has not
    written yet, or an update we never saw the start of. Not a failure."""
    assert await unsubscribe(session, 91999) is False


async def test_unsubscribing_keeps_every_column(session: AsyncSession) -> None:
    """The whole point. Opting out of being written to is not leaving, and the
    row is what makes somebody the same person if they come back.

    Every column the mapper knows about, asked for by name rather than listed
    here: a column added next year is one nobody would think to add to a list,
    and the first thing anybody would do with a new column is forget it.
    """
    user = await _person(session)
    columns = [
        column.key
        for column in User.__mapper__.columns
        if column.key != "unsubscribed_at"
    ]
    before = {name: getattr(user, name) for name in columns}

    await unsubscribe(session, user.tg_id)
    await session.flush()
    # Read back rather than trusted: the assertion is about what landed in the
    # row, and every attribute here is still in memory until something asks
    # the database. `refresh` and not `expire`, because an expired attribute
    # loads on the next read — which, outside an await, is a MissingGreenlet
    # rather than an answer.
    await session.refresh(user)

    kept = await session.scalar(select(User).where(User.tg_id == user.tg_id))
    assert kept is not None
    assert {name: getattr(kept, name) for name in columns} == before
    assert kept.unsubscribed_at is not None


async def test_unsubscribing_keeps_what_belongs_to_them(
    session: AsyncSession,
) -> None:
    """Their profile, their requests, and the answers to them.

    `User.helper` cascades `delete-orphan`, so a `session.delete` here would
    take the profile with it and this is the assertion that would say so.
    """
    user = await _person(session, tg_id=91002)
    session.add(HelperProfile(user_id=user.id, headline="Матан и линал"))
    request = HelpRequest(author_id=user.id, raw_text="нужен матан")
    session.add(request)
    await session.flush()
    session.add(RequestResponse(request_id=request.id, helper_id=user.id, message="могу"))
    await session.flush()

    await unsubscribe(session, user.tg_id)
    await session.flush()

    assert await session.get(HelperProfile, user.id) is not None
    assert (
        await session.scalar(
            select(func.count())
            .select_from(HelpRequest)
            .where(HelpRequest.author_id == user.id)
        )
        == 1
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(RequestResponse)
            .where(RequestResponse.helper_id == user.id)
        )
        == 1
    )


class _Message:
    """Just enough of an aiogram `Message` for the handler.

    A recorder rather than a mock: what is asserted is the text that would have
    reached Telegram, which is the only thing the handler produces.
    """

    def __init__(self, tg_id: int | None) -> None:
        self.from_user = SimpleNamespace(id=tg_id) if tg_id is not None else None
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, reply_markup: object = None, **_: object) -> None:
        self.answers.append(text)
        self.markups.append(reply_markup)


def _lend(session: AsyncSession):
    """Hand the handler this test's session instead of a new one.

    The handler opens its own — it has no request to hang a transaction on, and
    docs/architecture.md says so — which is exactly what makes it invisible to
    the rest of the suite. Lending the session is what lets the assertion below
    read what the handler wrote.
    """

    @asynccontextmanager
    async def scope():
        yield session

    return lambda: scope()


async def test_the_stop_handler_unsubscribes_and_says_so(
    session: AsyncSession, monkeypatch
) -> None:
    """The wiring. Every other test here would still pass if `on_stop` stopped
    calling the rule, stopped committing, or answered something else."""
    monkeypatch.setattr(students_cz_bot, "get_sessionmaker", lambda: _lend(session))
    user = await _person(session, tg_id=91003)
    message = _Message(user.tg_id)

    await students_cz_bot.on_stop(message)

    assert user.unsubscribed_at is not None
    assert message.answers == [UNSUBSCRIBED]


async def test_an_update_without_a_sender_is_ignored(
    session: AsyncSession, monkeypatch
) -> None:
    """Channel posts have no `from_user`. Nothing to unsubscribe and nobody to
    answer, which is a return rather than an exception."""
    monkeypatch.setattr(students_cz_bot, "get_sessionmaker", lambda: _lend(session))
    message = _Message(None)

    await students_cz_bot.on_stop(message)

    assert message.answers == []


class _Bot:
    """Records what the bot would have told Telegram about itself."""

    def __init__(self) -> None:
        self.commands: list[dict] = []
        self.menu_buttons: list[dict] = []

    async def set_my_commands(self, commands, **kwargs) -> None:
        self.commands.append({"commands": commands, **kwargs})

    async def set_chat_menu_button(self, **kwargs) -> None:
        self.menu_buttons.append(kwargs)


async def test_the_command_list_is_the_commands_that_exist() -> None:
    """This token belonged to a command-driven bot first.

    Telegram keeps the list until somebody replaces it, so a bot that sets none
    is still offering the old one — `/language`, which nothing here handles.
    """
    from students_cz.core.config import Settings

    bot = _Bot()
    await students_cz_bot.configure(
        cast(Bot, bot), Settings(_env_file=None, public_base_url="https://tests.example")
    )

    assert bot.commands, "nothing replaced the list the previous bot left"
    offered = {command.command for call in bot.commands for command in call["commands"]}
    assert offered == {"start", "stop"}


async def test_the_menu_is_still_pointed_at_the_app() -> None:
    from students_cz.core.config import Settings

    bot = _Bot()
    await students_cz_bot.configure(
        cast(Bot, bot), Settings(_env_file=None, public_base_url="https://tests.example")
    )

    [call] = bot.menu_buttons
    button = call["menu_button"]
    assert button.web_app.url == "https://tests.example"
    assert button.text


async def test_answering_anything_else_clears_the_old_keyboard() -> None:
    """The buttons of the previous bot are still in every chat it ever had.

    Nothing but a reply carrying `ReplyKeyboardRemove` takes them away, and
    tapping one is exactly what somebody with a stale keyboard does.
    """
    from aiogram.types import ReplyKeyboardRemove

    message = _Message(91004)

    await students_cz_bot.on_anything_else(message)

    assert message.answers
    assert isinstance(message.markups[-1], ReplyKeyboardRemove)


async def test_a_channel_post_is_not_answered() -> None:
    """No sender, nobody to have asked — the rule `on_stop` already follows."""
    message = _Message(None)

    await students_cz_bot.on_anything_else(message)

    assert message.answers == []


async def test_the_opt_out_reply_clears_the_old_keyboard_too(
    session: AsyncSession, monkeypatch
) -> None:
    from aiogram.types import ReplyKeyboardRemove

    monkeypatch.setattr(students_cz_bot, "get_sessionmaker", lambda: _lend(session))
    user = await _person(session, tg_id=91005)
    message = _Message(user.tg_id)

    await students_cz_bot.on_stop(message)

    assert isinstance(message.markups[-1], ReplyKeyboardRemove)


async def test_the_catch_all_answers_last_and_only_then() -> None:
    """Order is the whole safety of a handler with no filter.

    Registered before `/start`, it would answer "everything happens in the
    app" to somebody opening the bot for the first time — and the greeting,
    which is the one thing this bot exists to say, would never be sent.
    """
    handlers = students_cz_bot.router.message.handlers

    assert handlers[-1].callback is students_cz_bot.on_anything_else
    assert not handlers[-1].filters, "a catch-all with a filter is not a catch-all"
    assert [handler.callback for handler in handlers[:-1]] == [
        students_cz_bot.on_start,
        students_cz_bot.on_stop,
    ]
