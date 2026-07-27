"""The catalog as a visitor sees it: the home screen, a person, a contact."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from students_cz.api.deps import LangDep, SessionDep, UserDep
from students_cz.db.models import (
    Contact,
    HelperProfile,
)
from students_cz.db.models.enums import (
    PublishStatus,
    UserEventKind,
)
from students_cz.schemas import (
    ContactOut,
    HelperDetailOut,
    HomeOut,
)
from students_cz.services import catalog
from students_cz.services.people import log_event

router = APIRouter()


@router.get("/home", response_model=HomeOut, tags=["catalog"])
async def home(session: SessionDep, lang: LangDep, user: UserDep) -> HomeOut:
    people, things = await catalog.home_sections(session, lang)
    # The first screen stands in for "opened the app". Logging every request
    # would drown the signal in taxonomy fetches.
    await log_event(session, user.id, UserEventKind.APP_OPEN, lang=lang.value)
    return HomeOut(people=people, things=things)


@router.get("/helpers/{user_id}", response_model=HelperDetailOut, tags=["catalog"])
async def helper_detail(
    user_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> HelperDetailOut:
    detail = await catalog.helper_detail(session, user_id, lang)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such published profile")
    await log_event(session, user.id, UserEventKind.HELPER_VIEW, helper_id=user_id)
    return detail


@router.post(
    "/helpers/{user_id}/contact",
    response_model=ContactOut,
    tags=["catalog"],
)
async def start_contact(
    user_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> ContactOut:
    """Record that someone is about to write, and hand back the link.

    The conversation itself happens in Telegram, where both people already are.
    What we keep is that it started — which is the only honest basis for the
    response times and deal counts shown on a card. Self-reported numbers would
    be worth nothing.
    """
    if user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that is your own profile")

    helper = await session.scalar(
        select(HelperProfile)
        .where(HelperProfile.user_id == user_id)
        .options(selectinload(HelperProfile.user))
    )
    if helper is None or helper.status != PublishStatus.PUBLISHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such published profile")
    if not helper.user.tg_username:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this person has no public username"
        )

    session.add(Contact(student_id=user.id, helper_id=user_id, intro_text=None))
    await log_event(session, user.id, UserEventKind.CONTACT, helper_id=user_id)

    return ContactOut(telegram_url=f"https://t.me/{helper.user.tg_username}")
