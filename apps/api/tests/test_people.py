"""Remembering people, and knowing who may be written to.

The reason this matters is not analytics. Someone who presses start, reads the
description and closes Telegram is invisible to the mini app and is exactly the
person a future announcement is for — so the bot has to record them, and the
record has to say whether writing to them is still allowed.
"""

from datetime import UTC, datetime

import pytest
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from students_cz.bot.middleware import RememberUserMiddleware
from students_cz.core.config import get_settings
from students_cz.db.models import User, UserEvent
from students_cz.db.models.enums import UiLang, UserEventKind
from students_cz.services.people import mark_unreachable, reachable, remember

pytestmark = pytest.mark.asyncio

LANGS = ("ru", "cs", "en", "uk")


def update_from(tg_id: int, text: str, *, first_name: str = "Про") -> Update:
    return Update(
        update_id=tg_id,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=tg_id, type="private"),
            from_user=TgUser(
                id=tg_id, is_bot=False, first_name=first_name, language_code="ru"
            ),
            text=text,
        ),
    )


async def run_middleware(session, update: Update) -> None:
    """Drive the middleware against the test's own session."""

    class _Maker:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return session

                async def __aexit__(self_inner, *exc):
                    return False

            return _Ctx()

    middleware = RememberUserMiddleware(get_settings(), sessionmaker=_Maker())
    # An Update may carry any one of a dozen kinds of event; these all carry a
    # message, and saying so is what makes the next line readable.
    assert update.message is not None
    data = {
        "event_from_user": update.message.from_user,
        "event_update": update,
    }
    await middleware(lambda event, data: _noop(), update, data)


async def _noop() -> None:
    return None


async def test_pressing_start_records_the_person(session):
    from sqlalchemy import select

    await run_middleware(session, update_from(700001, "/start"))

    user = await session.scalar(select(User).where(User.tg_id == 700001))
    assert user is not None
    assert user.bot_started_at is not None, "start is what makes them writable to"
    assert user.bot_can_message is True

    kinds = (
        await session.scalars(select(UserEvent.kind).where(UserEvent.user_id == user.id))
    ).all()
    assert UserEventKind.BOT_START in kinds


async def test_a_deep_link_is_kept_as_the_source(session):
    from sqlalchemy import select

    await run_middleware(session, update_from(700002, "/start instagram_july"))
    user = await session.scalar(select(User).where(User.tg_id == 700002))
    assert user.source == "instagram_july"

    # Where they came from, not where they most recently came from.
    await run_middleware(session, update_from(700002, "/start telegram_ads"))
    await session.refresh(user)
    assert user.source == "instagram_july"


async def test_any_message_records_the_person_not_only_start(session):
    """Someone who writes "привет" is as real as someone who presses a button."""
    from sqlalchemy import select

    await run_middleware(session, update_from(700003, "привет"))
    user = await session.scalar(select(User).where(User.tg_id == 700003))
    assert user is not None
    # ...but they have not started the bot, so we may not write to them.
    assert user.bot_started_at is None


async def test_the_audience_is_only_people_we_may_write_to(session):
    from sqlalchemy import select

    started = await remember(
        session,
        tg_id=700010,
        first_name="Started",
        supported_langs=LANGS,
        started_bot=True,
    )
    never = await remember(
        session,
        tg_id=700011,
        first_name="Never",
        supported_langs=LANGS,
    )
    blocked = await remember(
        session,
        tg_id=700012,
        first_name="Blocked",
        supported_langs=LANGS,
        started_bot=True,
    )
    left = await remember(
        session,
        tg_id=700013,
        first_name="Left",
        supported_langs=LANGS,
        started_bot=True,
    )
    await session.flush()

    await mark_unreachable(session, 700012, reason="test")
    left.unsubscribed_at = datetime.now(UTC)
    await session.flush()

    audience = set((await session.scalars(reachable().with_only_columns(User.id))).all())
    assert started.id in audience
    assert never.id not in audience, "never pressed start — Telegram forbids it"
    assert blocked.id not in audience, "Telegram already told us they blocked us"
    assert left.id not in audience, "they asked us to stop"

    # And filtering the audience narrows it rather than widening it.
    by_source = select(User.id).where(User.id.in_(audience))
    assert set((await session.scalars(by_source)).all()) == audience


async def test_being_blocked_is_recorded_once(session):
    from sqlalchemy import func, select

    user = await remember(
        session, tg_id=700020, first_name="B", supported_langs=LANGS, started_bot=True
    )
    await session.flush()

    await mark_unreachable(session, 700020, reason="forbidden")
    await mark_unreachable(session, 700020, reason="forbidden")
    await session.flush()

    events = await session.scalar(
        select(func.count(UserEvent.id)).where(
            UserEvent.user_id == user.id, UserEvent.kind == UserEventKind.BOT_BLOCKED
        )
    )
    assert events == 1, "a second 403 for the same person is not new information"


async def test_starting_again_makes_someone_reachable_once_more(session):
    """Blocking and unblocking is how people come back."""
    from sqlalchemy import select

    await remember(
        session,
        tg_id=700021,
        first_name="Back",
        supported_langs=LANGS,
        started_bot=True,
    )
    await session.flush()
    await mark_unreachable(session, 700021, reason="forbidden")
    await session.flush()

    await run_middleware(session, update_from(700021, "/start"))
    user = await session.scalar(select(User).where(User.tg_id == 700021))
    assert user.bot_can_message is True


async def test_an_unknown_institution_is_named_rather_than_a_foreign_key_error(
    session,
):
    from students_cz.schemas import MeUpdate
    from students_cz.services import errors
    from students_cz.services.people import update_profile

    user = User(tg_id=700030, first_name="Nina", ui_lang=UiLang.RU)
    session.add(user)
    await session.flush()

    with pytest.raises(errors.Invalid):
        await update_profile(session, user, MeUpdate(institution_id=10**9))


async def test_a_field_the_payload_does_not_mention_is_left_alone(session):
    """What the form did not ask about, the save does not answer.

    The same rule as the helper profile: a screen that shows three fields must
    not clear the fourth on its way out.
    """
    from students_cz.schemas import MeUpdate
    from students_cz.services.people import update_profile

    user = User(
        tg_id=700031,
        first_name="Oleg",
        ui_lang=UiLang.RU,
        spoken_langs=["ru", "cs"],
        city="Praha",
    )
    session.add(user)
    await session.flush()

    await update_profile(session, user, MeUpdate(ui_lang=UiLang.CS))

    assert user.ui_lang is UiLang.CS
    assert user.city == "Praha"
    assert user.spoken_langs == ["ru", "cs"]


async def test_a_full_name_is_both_parts_and_falls_back_to_the_id():
    """Not the catalog's rule — a card shows a first name and an initial."""
    from students_cz.services.people import full_name

    assert (
        full_name(User(tg_id=1, first_name="Нина", last_name="К", ui_lang=UiLang.RU))
        == "Нина К"
    )
    assert full_name(User(tg_id=2, first_name="Нина", ui_lang=UiLang.RU)) == "Нина"
