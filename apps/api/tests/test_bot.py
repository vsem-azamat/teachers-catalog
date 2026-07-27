"""What the bot says, and what saying it costs somebody.

The copy is tested here because it is a claim about the code. A sentence
telling somebody how to undo something is a promise, and the only person who
finds out that it is empty is the one who tried it.
"""

import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.bot import GREETING, UNSUBSCRIBED
from konnekt.db.models import User
from konnekt.db.models.enums import UiLang
from konnekt.services.people import unsubscribe

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


async def test_unsubscribing_keeps_everything_else(session: AsyncSession) -> None:
    """The whole point. Opting out of being written to is not leaving, and the
    row is what makes somebody the same person if they come back."""
    user = await _person(session)
    before = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "tg_username": user.tg_username,
        "ui_lang": user.ui_lang,
        "source": user.source,
        "bot_started_at": user.bot_started_at,
        "is_blocked": user.is_blocked,
    }

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
    assert {key: getattr(kept, key) for key in before} == before
    assert kept.unsubscribed_at is not None
