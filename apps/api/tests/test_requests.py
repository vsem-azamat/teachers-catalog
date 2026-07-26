"""The other direction: a student asks, a helper answers.

The catalog side is tested in test_api; this covers the loop that only exists
once someone can reply — who may see incoming requests, who may answer them,
and what the author sees afterwards.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.db.models import Contact, HelperProfile, HelpRequest, User
from konnekt.db.models.enums import PublishStatus, RequestStatus

from .conftest import auth_header

STUDENT = 90501
HELPER = 90502
OTHER = 90503

pytestmark = pytest.mark.asyncio


def helper_header(tg_id: int = HELPER, **extra) -> dict[str, str]:
    """A helper, with the public username answering a request now requires."""
    return auth_header(tg_id, username=f"helper{tg_id}", **extra)


async def post_request(client: AsyncClient, text: str, tg_id: int = STUDENT) -> dict:
    response = await client.post(
        "/api/v1/requests", json={"text": text}, headers=auth_header(tg_id)
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── who may look ────────────────────────────────────────────────────────


async def test_feed_refuses_someone_with_no_profile(client: AsyncClient) -> None:
    response = await client.get("/api/v1/requests/feed", headers=auth_header(OTHER))
    assert response.status_code == 403


async def test_draft_helper_may_look_but_not_answer(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Seeing the demand is the argument for finishing the profile."""
    created = await post_request(client, "нужна помощь с матаном, ЧВУТ")
    helper = await helper_factory(tg_id=HELPER)
    profile = await session.get(HelperProfile, helper.id)
    profile.status = PublishStatus.DRAFT
    await session.commit()

    feed = await client.get("/api/v1/requests/feed", headers=helper_header())
    assert feed.status_code == 200
    assert created["id"] in [item["id"] for item in feed.json()]

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 403


async def test_feed_hides_your_own_requests(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    mine = await post_request(client, "ищу помощь с матаном", tg_id=HELPER)

    feed = await client.get("/api/v1/requests/feed", headers=helper_header())
    assert mine["id"] not in [item["id"] for item in feed.json()]


async def test_feed_ranks_your_subject_first_and_says_why(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A request about what you teach outranks one posted more recently."""
    await helper_factory(tg_id=HELPER, subject_slug="matematicka-analyza")
    on_subject = await post_request(client, "матан ЧВУТ, экзамен через неделю")
    # Posted after, so only relevance can put the other one first.
    await post_request(client, "нужен фотограф на выпускной")

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert feed[0]["id"] == on_subject["id"]
    assert feed[0]["reason"]["code"] == "feed.same_subject"
    # The author is shown; who else is bidding is not.
    assert feed[0]["author_name"]
    assert "responders" not in feed[0] or feed[0]["responders"] == []


async def test_feed_drops_a_request_you_already_answered(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан, нужна помощь")

    answered = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "помогу, готовил к этому экзамену"},
        headers=helper_header(),
    )
    assert answered.status_code == 201, answered.text

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert created["id"] not in [item["id"] for item in feed]


async def test_feed_hides_closed_requests(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан срочно")
    await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert created["id"] not in [item["id"] for item in feed]


# ── answering ───────────────────────────────────────────────────────────


async def test_answering_shows_up_for_the_author(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER, first_name="Marek")
    created = await post_request(client, "матан, ЧВУТ, экзамен 14 февраля")

    # The name comes from initData, not from our row: Telegram owns it, and
    # `remember` overwrites what the fixture invented on every call.
    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "готовил к этому экзамену, могу помочь", "price_amount": 500},
        headers=helper_header(first_name="Marek"),
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["price"]["amount"] == 500
    assert answer.json()["status"] == "sent"

    listed = await client.get(
        f"/api/v1/requests/{created['id']}/responses", headers=auth_header(STUDENT)
    )
    assert listed.status_code == 200
    [row] = listed.json()
    assert row["name"].startswith("Marek")
    assert row["message"].startswith("готовил")

    mine = (await client.get("/api/v1/requests", headers=auth_header(STUDENT))).json()
    assert mine[0]["responses_count"] == 1


async def test_reading_the_answers_marks_them_read(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь с этим"},
        headers=helper_header(),
    )

    first = await client.get(
        f"/api/v1/requests/{created['id']}/responses", headers=auth_header(STUDENT)
    )
    assert first.json()[0]["status"] == "sent"

    second = await client.get(
        f"/api/v1/requests/{created['id']}/responses", headers=auth_header(STUDENT)
    )
    assert second.json()[0]["status"] == "read"


async def test_answering_twice_is_refused(client: AsyncClient, helper_factory) -> None:
    """One answer per helper. Repeat pitching is spam."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    body = {"message": "могу помочь с матаном"}

    first = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json=body,
        headers=helper_header(),
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json=body,
        headers=helper_header(),
    )
    assert second.status_code == 409


async def test_answering_your_own_request_is_refused(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    mine = await post_request(client, "матан", tg_id=HELPER)

    answer = await client.post(
        f"/api/v1/requests/{mine['id']}/respond",
        json={"message": "сам себе помогу"},
        headers=helper_header(),
    )
    assert answer.status_code == 400


async def test_answering_a_closed_request_is_refused(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 409


async def test_an_expired_request_cannot_be_answered(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Open but past its deadline is closed in every way that matters."""
    from datetime import UTC, datetime, timedelta

    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан, экзамен завтра")
    request = await session.get(HelpRequest, created["id"])
    request.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert created["id"] not in [item["id"] for item in feed]

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 409


# ── the author's side ───────────────────────────────────────────────────


async def test_answers_are_not_a_public_bid_list(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )

    # Not the author, and not even the helper who answered.
    for tg_id in (OTHER, HELPER):
        peeking = await client.get(
            f"/api/v1/requests/{created['id']}/responses", headers=auth_header(tg_id)
        )
        assert peeking.status_code == 404


async def test_accepting_records_a_contact_and_leaves_the_request_open(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = (
        await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь"},
            headers=helper_header(),
        )
    ).json()

    accepted = await client.post(
        f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(STUDENT)
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    student = await session.scalar(select(User).where(User.tg_id == STUDENT))
    contact = await session.scalar(
        select(Contact).where(
            Contact.student_id == student.id, Contact.helper_id == helper.id
        )
    )
    assert contact is not None
    assert contact.request_id == created["id"]

    # Needing two people for two subjects is ordinary.
    request = await session.get(HelpRequest, created["id"])
    await session.refresh(request)
    assert request.status is RequestStatus.OPEN


async def test_only_the_author_may_accept(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = (
        await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь"},
            headers=helper_header(),
        )
    ).json()

    for tg_id in (OTHER, HELPER):
        stolen = await client.post(
            f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(tg_id)
        )
        assert stolen.status_code == 404


async def test_declining(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = (
        await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь"},
            headers=helper_header(),
        )
    ).json()

    declined = await client.post(
        f"/api/v1/responses/{answer['id']}/decline", headers=auth_header(STUDENT)
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "declined"


# ── what the review of this feature turned up ───────────────────────────


async def _answer(client: AsyncClient, request_id: int, tg_id: int = HELPER) -> dict:
    response = await client.post(
        f"/api/v1/requests/{request_id}/respond",
        json={"message": "могу помочь с этим"},
        headers=helper_header(tg_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_banned_profile_cannot_read_the_feed(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """The feed is names, faces and budgets — a target list for a banned account."""
    await post_request(client, "матан, ЧВУТ")
    helper = await helper_factory(tg_id=HELPER)
    profile = await session.get(HelperProfile, helper.id)
    profile.status = PublishStatus.BANNED
    await session.commit()

    feed = await client.get("/api/v1/requests/feed", headers=helper_header())
    assert feed.status_code == 403


async def test_answering_needs_a_public_username(
    client: AsyncClient, helper_factory
) -> None:
    """Without one the author has nowhere to write, so the deal is a dead end."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        # No username in the init data.
        headers=auth_header(HELPER),
    )
    assert answer.status_code == 409
    assert "username" in answer.json()["detail"]


async def test_a_blank_answer_is_refused(client: AsyncClient, helper_factory) -> None:
    """min_length sees the raw string; "   " would be stored as an empty message."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "     "},
        headers=helper_header(),
    )
    assert answer.status_code == 422


async def test_accepting_twice_records_one_contact(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A double tap must not invent a second deal, or a second notification."""
    helper = await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = await _answer(client, created["id"])

    for _ in range(3):
        accepted = await client.post(
            f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(STUDENT)
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"

    student = await session.scalar(select(User).where(User.tg_id == STUDENT))
    contacts = await session.scalar(
        select(func.count(Contact.id)).where(
            Contact.student_id == student.id, Contact.helper_id == helper.id
        )
    )
    assert contacts == 1


async def test_an_accepted_answer_cannot_be_declined(
    client: AsyncClient, helper_factory
) -> None:
    """Otherwise the author reads "declined" while the helper reads "chosen"."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = await _answer(client, created["id"])

    await client.post(
        f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(STUDENT)
    )
    declined = await client.post(
        f"/api/v1/responses/{answer['id']}/decline", headers=auth_header(STUDENT)
    )
    assert declined.status_code == 409


async def test_the_feed_does_not_say_how_many_others_answered(
    client: AsyncClient, helper_factory
) -> None:
    """A helper who can see "already contested" simply skips those."""
    await helper_factory(tg_id=HELPER)
    await helper_factory(tg_id=OTHER, first_name="Petra")
    created = await post_request(client, "матан")
    await _answer(client, created["id"], tg_id=OTHER)

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [row] = [item for item in feed if item["id"] == created["id"]]
    assert "responses_count" not in row
    assert "responders" not in row
