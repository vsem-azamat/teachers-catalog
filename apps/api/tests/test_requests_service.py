"""Who sees the feed, and in what order — without an HTTP client.

The feed is the second-largest algorithm in the product: a helper is shown
open requests ranked by how well they match what they actually offer. Both
halves of it are rules, not rendering, so both belong somewhere a test can
reach directly.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.db.models import (
    HelperProfile,
    HelpRequest,
    Institution,
    Offer,
    ServiceType,
    Subject,
    User,
)
from konnekt.db.models.enums import PublishStatus, RequestStatus, UiLang
from konnekt.services import errors
from konnekt.services import requests as requests_service

pytestmark = pytest.mark.asyncio


async def _person(session: AsyncSession, tg_id: int) -> User:
    user = User(tg_id=tg_id, first_name="Marek", ui_lang=UiLang.RU)
    session.add(user)
    await session.flush()
    return user


async def _ask(session: AsyncSession, author: User, text: str, **extra) -> HelpRequest:
    request = HelpRequest(
        author_id=author.id,
        raw_text=text,
        status=RequestStatus.OPEN,
        langs=["ru"],
        **extra,
    )
    session.add(request)
    await session.flush()
    return request


async def test_somebody_with_no_helper_profile_is_refused(
    session: AsyncSession,
) -> None:
    user = await _person(session, 91201)
    with pytest.raises(errors.Forbidden):
        await requests_service.feed_for(session, user=user, limit=20)


async def test_a_draft_profile_may_look(session: AsyncSession) -> None:
    """Seeing that four people want your subject is the argument for finishing
    the profile; withholding it until published gets that backwards."""
    user = await _person(session, 91202)
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.DRAFT))
    await session.flush()

    assert await requests_service.feed_for(session, user=user, limit=20) is not None


async def test_a_banned_profile_is_refused(session: AsyncSession) -> None:
    """The feed carries every author's name, photo, text and budget."""
    user = await _person(session, 91203)
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.BANNED))
    await session.flush()

    with pytest.raises(errors.Forbidden):
        await requests_service.feed_for(session, user=user, limit=20)


async def test_your_own_requests_are_not_in_your_feed(session: AsyncSession) -> None:
    user = await _person(session, 91204)
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.PUBLISHED))
    await session.flush()
    mine = await _ask(session, user, "мой собственный вопрос")

    rows = await requests_service.feed_for(session, user=user, limit=50)
    assert mine.id not in {row.request.id for row in rows}


async def test_a_closed_request_is_not_in_the_feed(session: AsyncSession) -> None:
    helper = await _person(session, 91205)
    session.add(HelperProfile(user_id=helper.id, status=PublishStatus.PUBLISHED))
    student = await _person(session, 91206)
    await session.flush()

    closed = await _ask(session, student, "уже не нужно")
    closed.status = RequestStatus.CLOSED
    await session.flush()

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    assert closed.id not in {row.request.id for row in rows}


async def test_a_row_says_which_axes_it_matched(session: AsyncSession) -> None:
    """The reason line is rendered from these three flags, so they are the
    contract — not the sentence built out of them."""
    helper = await _person(session, 91207)
    session.add(HelperProfile(user_id=helper.id, status=PublishStatus.PUBLISHED))
    student = await _person(session, 91208)
    await session.flush()
    asked = await _ask(session, student, "нужен матан")

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    [row] = [item for item in rows if item.request.id == asked.id]
    assert row.on_subject is False
    assert row.on_institution is False
    assert row.on_service is False
    assert row.author.id == student.id


async def test_a_request_on_your_subject_outranks_one_that_is_not(
    session: AsyncSession,
) -> None:
    """The ranking, not just the reason line.

    Both requests are open and answerable; the only difference is that one
    names a subject this helper offers. If the ORDER BY is lost, the two come
    back in insertion order and this fails — which is the point, because a
    silently reordered feed fails nothing else.
    """
    helper = await _person(session, 91209)
    student = await _person(session, 91210)
    session.add(HelperProfile(user_id=helper.id, status=PublishStatus.PUBLISHED))
    await session.flush()

    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "tutoring")
    )
    subject_id = await session.scalar(select(Subject.id).limit(1))
    assert service_type_id is not None and subject_id is not None

    session.add(
        Offer(
            helper_id=helper.id,
            service_type_id=service_type_id,
            subject_id=subject_id,
            is_active=True,
        )
    )

    # The matching one is written *first*, so every tiebreak works against it:
    # rows written in one transaction share created_at, and the id tiebreak is
    # descending. Only the ranking can lift it, which is what makes this a test
    # of the ranking rather than of insertion order.
    on_subject = await _ask(session, student, "мой предмет", subject_id=subject_id)
    unrelated = await _ask(session, student, "что-то другое")

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    ordered = [
        row.request.id for row in rows if row.request.id in {unrelated.id, on_subject.id}
    ]

    assert ordered == [on_subject.id, unrelated.id]
    matched = next(row for row in rows if row.request.id == on_subject.id)
    assert matched.on_subject is True


async def test_your_own_faculty_counts_even_without_an_offer_for_it(
    session: AsyncSession,
) -> None:
    """A request from your own school is relevant whether or not you listed it."""
    institution_id = await session.scalar(select(Institution.id).limit(1))
    assert institution_id is not None

    helper = await _person(session, 91211)
    helper.institution_id = institution_id
    student = await _person(session, 91212)
    session.add(HelperProfile(user_id=helper.id, status=PublishStatus.PUBLISHED))
    await session.flush()

    asked = await _ask(session, student, "с факультета", institution_id=institution_id)

    rows = await requests_service.feed_for(session, user=helper, limit=50)
    [row] = [item for item in rows if item.request.id == asked.id]
    assert row.on_institution is True
