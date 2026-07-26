from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.core.config import Settings, get_settings
from konnekt.core.security import InitDataError, TelegramIdentity, parse_init_data
from konnekt.db.models import User
from konnekt.db.models.enums import UiLang
from konnekt.db.session import session_scope
from konnekt.services.people import remember

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(session_scope, scope="function")]


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
    authenticated request is the registration. The same function the bot uses,
    so that a person recorded through one door is the same row as through the
    other.
    """
    user = await remember(
        session,
        tg_id=identity.tg_id,
        first_name=identity.first_name,
        last_name=identity.last_name,
        username=identity.username,
        language_code=identity.language_code,
        photo_url=identity.photo_url,
        supported_langs=settings.supported_ui_langs,
        source=identity.start_param,
    )
    # The one write that outlives a failed request, deliberately. Telegram is
    # the identity provider and the first authenticated request is the
    # registration, so first sight of a person — and the `source` that says
    # where they came from — should survive whatever the handler goes on to do
    # with them. It also releases the lock on the users unique index, which the
    # mini app's several parallel opening requests would otherwise queue on.
    await session.commit()

    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account is blocked")
    return user


UserDep = Annotated[User, Depends(current_user)]


async def current_lang(user: UserDep) -> UiLang:
    return user.ui_lang


LangDep = Annotated[UiLang, Depends(current_lang)]
