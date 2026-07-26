"""The helper's own profile: reading it back, and publishing without a subject.

Two changes are under test here. `GET /helper` is a new door onto a profile
that `/helpers/{id}` deliberately refuses to open — drafts and hidden ones —
because the person who wrote it has to be able to read it back. And publishing
no longer requires a recognised subject: the catalog needs people in it before
it needs them classified.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.db.models import HelperProfile, Offer, ServiceType, Subject
from konnekt.db.models.enums import PublishStatus

from .conftest import auth_header

pytestmark = pytest.mark.asyncio

OWNER = 91501


async def test_no_profile_answers_with_an_empty_shell(client: AsyncClient) -> None:
    """Not a 404: the screen behind this is a form, and a form always renders."""
    response = await client.get("/api/v1/helper", headers=auth_header(OWNER))

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["status"] is None
    assert body["offers"] == []


async def test_reading_your_own_profile_needs_init_data(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/helper")).status_code == 401


async def test_a_draft_reads_back_with_ids_and_names(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A draft is invisible in the catalog and must still be editable."""
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    service = await session.scalar(select(ServiceType).where(ServiceType.code == "tutoring"))
    assert subject is not None and service is not None

    # Register the caller, then hand them a draft with one offer.
    await client.get("/api/v1/me", headers=auth_header(OWNER))
    from konnekt.db.models import User

    user = await session.scalar(select(User).where(User.tg_id == OWNER))
    assert user is not None
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.DRAFT, about="Учу"))
    session.add(
        Offer(
            helper_id=user.id,
            service_type_id=service.id,
            subject_id=subject.id,
            price_amount=550,
            langs=["ru"],
        )
    )
    await session.flush()

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()

    assert body["exists"] is True
    assert body["status"] == "draft"
    assert body["about"] == "Учу"
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    # Both halves: the id is what goes back on save, the name is what is read.
    assert offer["subject_id"] == subject.id
    assert offer["subject_name"]
    assert offer["service_type"] == "tutoring"
    assert offer["price_amount"] == 550


async def test_publishing_without_a_single_subject_is_allowed(
    client: AsyncClient,
) -> None:
    """The parser is no longer the gatekeeper.

    Someone teaching something the taxonomy has never heard of used to write a
    paragraph and watch the button stay grey. Now they get in, and the subject
    is a thing they add later.
    """
    saved = await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Помогу с чем угодно по математике", "publish": True},
    )

    assert saved.status_code == 200
    assert saved.json()["helper_status"] == "published"

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert body["exists"] is True
    assert body["offers"] == []


async def test_hiding_a_published_profile_keeps_it_readable(
    client: AsyncClient,
) -> None:
    """"Hide me" has to take it out of the catalog, not out of the person's hands."""
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Первая версия", "publish": True},
    )
    await client.put(
        "/api/v1/helper",
        headers=auth_header(OWNER),
        json={"about": "Первая версия", "publish": False},
    )

    body = (await client.get("/api/v1/helper", headers=auth_header(OWNER))).json()
    assert body["status"] == "hidden"
    assert body["about"] == "Первая версия"
