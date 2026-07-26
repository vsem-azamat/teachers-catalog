from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.core.config import Settings, get_settings
from konnekt.core.security import InitDataError, TelegramIdentity, parse_init_data
from konnekt.db.models import User
from konnekt.db.models.enums import UiLang
from konnekt.db.session import session_scope

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(session_scope)]


def _extract_init_data(authorization: str | None) -> str:
    """Read the `Authorization: tma <initData>` header.

    The `tma` scheme is the convention the Telegram SDKs use. initData must not
    travel as a query parameter — it would end up in proxy and access logs.
    """
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Authorization header")
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma" or not raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "expected 'Authorization: tma <initData>'"
        )
    return raw


async def current_identity(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramIdentity:
    try:
        return parse_init_data(_extract_init_data(authorization), settings)
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


IdentityDep = Annotated[TelegramIdentity, Depends(current_identity)]


async def current_user(
    identity: IdentityDep,
    session: SessionDep,
    settings: SettingsDep,
) -> User:
    """Fetch the caller, creating the row on first sight.

    Telegram is the identity provider, so there is no sign-up: the first
    authenticated request is the registration. Profile fields Telegram owns
    (name, username, avatar) are refreshed on every visit, since they change
    outside our reach and a stale username breaks the "write to them" link.
    """
    user = await session.scalar(select(User).where(User.tg_id == identity.tg_id))

    if user is None:
        user = User(
            tg_id=identity.tg_id,
            first_name=identity.first_name,
            last_name=identity.last_name,
            tg_username=identity.username,
            photo_url=identity.photo_url,
            ui_lang=_pick_ui_lang(identity.language_code, settings),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    changed = False
    for field, value in (
        ("first_name", identity.first_name),
        ("last_name", identity.last_name),
        ("tg_username", identity.username),
        ("photo_url", identity.photo_url),
    ):
        if value is not None and getattr(user, field) != value:
            setattr(user, field, value)
            changed = True
    if changed:
        await session.commit()

    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account is blocked")
    return user


UserDep = Annotated[User, Depends(current_user)]


def _pick_ui_lang(language_code: str | None, settings: Settings) -> UiLang:
    """Map Telegram's IETF tag onto a language we actually ship.

    Telegram may send a region (`en-US`), so only the primary subtag matters.
    """
    if language_code:
        primary = language_code.split("-", 1)[0].lower()
        if primary in settings.supported_ui_langs:
            return UiLang(primary)
    return UiLang(settings.default_ui_lang)


async def current_lang(user: UserDep) -> UiLang:
    return user.ui_lang


LangDep = Annotated[UiLang, Depends(current_lang)]
