"""The helper profile rules, reached without an HTTP client.

This is the point of the service layer and the reason the extraction was
worth doing: the publish state machine and the offer diff are the riskiest
write in the application, and until now the only way to exercise either was a
signed request against a running app.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import HelperProfile, Offer, ServiceType, User
from students_cz.db.models.enums import PublishStatus, UiLang
from students_cz.schemas import HelperUpsert, OfferIn
from students_cz.services import errors, helpers

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


async def test_a_save_that_says_nothing_about_offers_keeps_them(
    session: AsyncSession,
) -> None:
    """`offers` follows the same rule as every other field: omitted is not empty.

    The list has a default of `[]`, so a caller that only wanted to change a
    headline used to delete everything the person offers. Both screens that
    exist today happen to send the list every time, which is the only reason
    this has never happened — and the docstring on `save_profile` already
    promises the opposite.
    """
    user = await _person(session, 91104)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "writing")
    )
    assert service_type_id is not None, "the seed should have this service type"

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(
            offers=[OfferIn(service_type_id=service_type_id, price_amount=4000)]
        ),
        lang=UiLang.RU,
    )
    await session.flush()

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(headline="ČVUT FEL"),
        lang=UiLang.RU,
    )
    await session.flush()

    kept = (await session.scalars(select(Offer).where(Offer.helper_id == user.id))).all()
    assert [row.service_type_id for row in kept] == [service_type_id]


async def test_an_explicitly_empty_offer_list_still_clears_them(
    session: AsyncSession,
) -> None:
    """The other half of the rule: sent-and-empty means "I have none now"."""
    user = await _person(session, 91105)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "writing")
    )
    assert service_type_id is not None

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(
            offers=[OfferIn(service_type_id=service_type_id, price_amount=4000)]
        ),
        lang=UiLang.RU,
    )
    await session.flush()

    await helpers.save_profile(
        session, user=user, spec=HelperUpsert(offers=[]), lang=UiLang.RU
    )
    await session.flush()

    left = (await session.scalars(select(Offer).where(Offer.helper_id == user.id))).all()
    assert left == []


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
