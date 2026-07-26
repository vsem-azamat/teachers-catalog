"""The helper profile rules, reached without an HTTP client.

This is the point of the service layer and the reason the extraction was
worth doing: the publish state machine and the offer diff are the riskiest
write in the application, and until now the only way to exercise either was a
signed request against a running app.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.api.schemas import HelperUpsert, OfferIn
from konnekt.db.models import HelperProfile, ServiceType, User
from konnekt.db.models.enums import PublishStatus, UiLang
from konnekt.services import errors, helpers

pytestmark = pytest.mark.asyncio


async def _person(session: AsyncSession, tg_id: int) -> User:
    user = User(tg_id=tg_id, first_name="Marek", ui_lang=UiLang.RU)
    session.add(user)
    await session.flush()
    return user


async def test_a_banned_profile_cannot_publish_itself(session: AsyncSession) -> None:
    user = await _person(session, 91101)
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.BANNED))
    await session.flush()

    with pytest.raises(errors.Forbidden):
        await helpers.save_profile(
            session,
            user=user,
            spec=HelperUpsert(raw_intro="пусти меня обратно", publish=True),
            lang=UiLang.RU,
        )


async def test_the_same_axes_twice_is_named_rather_than_a_constraint_error(
    session: AsyncSession,
) -> None:
    user = await _person(session, 91102)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "exam_live_help")
    )
    assert service_type_id is not None, "the seed should have this service type"
    offer = OfferIn(service_type_id=service_type_id, price_amount=500)

    with pytest.raises(errors.Invalid) as raised:
        await helpers.save_profile(
            session,
            user=user,
            spec=HelperUpsert(raw_intro="матан", offers=[offer, offer]),
            lang=UiLang.RU,
        )
    assert "duplicate offer" in str(raised.value)


async def test_hiding_a_profile_that_was_published_keeps_it_hidden_not_draft(
    session: AsyncSession,
) -> None:
    user = await _person(session, 91103)

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(raw_intro="матан", publish=True),
        lang=UiLang.RU,
    )
    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(raw_intro="матан", publish=False),
        lang=UiLang.RU,
    )

    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    assert profile.status is PublishStatus.HIDDEN
