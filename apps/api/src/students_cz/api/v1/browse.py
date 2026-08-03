"""The catalog as a visitor sees it: the home screen, a person, a contact."""

from fastapi import APIRouter, HTTPException, status

from students_cz.api.deps import LangDep, SessionDep, UserDep
from students_cz.schemas import (
    ContactOut,
    HelperDetailOut,
    HomeOut,
)
from students_cz.services import catalog

router = APIRouter()


@router.get("/home", response_model=HomeOut, tags=["catalog"])
async def home(session: SessionDep, lang: LangDep, user: UserDep) -> HomeOut:
    people, things = await catalog.open_home(session, lang, viewer=user)
    return HomeOut(people=people, things=things)


@router.get("/helpers/{user_id}", response_model=HelperDetailOut, tags=["catalog"])
async def helper_detail(
    user_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> HelperDetailOut:
    detail = await catalog.view_helper(session, user_id, lang, viewer=user)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such published profile")
    return detail


@router.post(
    "/helpers/{user_id}/contact",
    response_model=ContactOut,
    tags=["catalog"],
)
async def start_contact(user_id: int, session: SessionDep, user: UserDep) -> ContactOut:
    """Record that someone is about to write, and hand back the link.

    The rule is `catalog.start_contact`. This sentence stays here because it is
    the operation's description in the OpenAPI document, which the client is
    generated from.
    """
    return await catalog.start_contact(session, viewer=user, helper_id=user_id)
