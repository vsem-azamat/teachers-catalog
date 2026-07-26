"""The account behind the init data: who you are, and what you chose."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from konnekt.api.deps import LangDep, SessionDep, UserDep
from konnekt.api.schemas import (
    MeOut,
    MeUpdate,
)
from konnekt.api.v1._shared import require_row
from konnekt.api.v1.taxonomy import institution_out
from konnekt.db.models import (
    HelperProfile,
    Institution,
)
from konnekt.services.catalog import avatar_for

router = APIRouter()


@router.get("/me", response_model=MeOut, tags=["me"])
async def read_me(user: UserDep, session: SessionDep, lang: LangDep) -> MeOut:
    helper = await session.get(HelperProfile, user.id)
    institution = None
    if user.institution_id:
        row = await session.scalar(
            select(Institution)
            .where(Institution.id == user.institution_id)
            .options(selectinload(Institution.names))
        )
        if row:
            institution = institution_out(row, lang)

    return MeOut(
        id=user.id,
        tg_id=user.tg_id,
        name=" ".join(filter(None, (user.first_name, user.last_name))),
        username=user.tg_username,
        avatar=avatar_for(user),
        ui_lang=user.ui_lang,
        spoken_langs=list(user.spoken_langs),
        city=user.city,
        institution=institution,
        is_helper=helper is not None,
        helper_status=helper.status.value if helper else None,
    )


@router.patch("/me", response_model=MeOut, tags=["me"])
async def update_me(
    payload: MeUpdate, user: UserDep, session: SessionDep, lang: LangDep
) -> MeOut:
    if payload.ui_lang is not None:
        user.ui_lang = payload.ui_lang
    if payload.spoken_langs is not None:
        user.spoken_langs = payload.spoken_langs
    if payload.city is not None:
        user.city = payload.city or None
    if payload.institution_id is not None:
        await require_row(
            session, Institution, payload.institution_id or None, "institution_id"
        )
        user.institution_id = payload.institution_id or None
    await session.commit()
    return await read_me(user, session, payload.ui_lang or lang)
