"""What the operator reads in the console. Reads only.

See docs/architecture.md, «The operator reads, and only reads».
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import HelperProfile, Offer, ServiceType, User
from students_cz.db.models.enums import (
    PlacementEventKind,
    PublishStatus,
    RequestStatus,
    UiLang,
)
from students_cz.db.models.ops import SearchQuery
from students_cz.db.models.partners import PartnerOffer, Placement, PlacementEvent
from students_cz.db.models.requests import HelpRequest, RequestResponse
from students_cz.schemas import (
    AdminCatalog,
    AdminCounts,
    AdminPlacement,
    AdminProfile,
    AdminRequest,
    AdminSearch,
)
from students_cz.services.catalog import display_name
from students_cz.services.naming import names_by_id
from students_cz.services.placements import offer_text
from students_cz.services.requests import live

WEEK = timedelta(days=7)
MONTH = timedelta(days=30)
# Enough to read on a phone; the counts say how long the full lists are.
LIST_CAP = 50
SEARCH_CAP = 20


async def catalog(session: AsyncSession, lang: UiLang) -> AdminCatalog:
    now = datetime.now(UTC)
    new_profile = and_(
        HelperProfile.status == PublishStatus.PUBLISHED,
        HelperProfile.published_at >= now - WEEK,
    )
    unanswered = and_(
        live(now), ~exists().where(RequestResponse.request_id == HelpRequest.id)
    )
    failed_search = and_(
        SearchQuery.results_count == 0, SearchQuery.created_at >= now - MONTH
    )
    return AdminCatalog(
        profiles=await _new_profiles(session, lang, new_profile),
        unanswered=await _unanswered(session, unanswered),
        failed_searches=await _failed_searches(session, failed_search),
        counts=AdminCounts(
            profiles_week=await _count(session, HelperProfile.user_id, new_profile),
            requests_week=await _count(
                session,
                HelpRequest.id,
                and_(
                    HelpRequest.status != RequestStatus.DRAFT,
                    HelpRequest.created_at >= now - WEEK,
                ),
            ),
            unanswered=await _count(session, HelpRequest.id, unanswered),
            failed_searches=await _count(
                session, func.distinct(_search_key()), failed_search
            ),
        ),
    )


async def _count(
    session: AsyncSession, what: ColumnElement[Any], where: ColumnElement[bool]
) -> int:
    return await session.scalar(select(func.count(what)).where(where)) or 0


async def _new_profiles(
    session: AsyncSession, lang: UiLang, where: ColumnElement[bool]
) -> list[AdminProfile]:
    rows = (
        await session.execute(
            select(HelperProfile.published_at, User)
            .join(User, User.id == HelperProfile.user_id)
            .where(where)
            .order_by(HelperProfile.published_at.desc())
            .limit(LIST_CAP)
        )
    ).all()
    ids = [user.id for _, user in rows]
    # What the catalog lists for them: a service switched off is not offered.
    offered = (
        await session.execute(
            select(Offer.helper_id, Offer.service_type_id)
            .where(Offer.helper_id.in_(ids), Offer.is_active.is_(True))
            .order_by(Offer.id)
        )
    ).all()
    names = await names_by_id(
        session, ServiceType, {service for _, service in offered}, lang
    )
    services: dict[int, list[str]] = {}
    for helper_id, service_id in offered:
        listed = services.setdefault(helper_id, [])
        if names.get(service_id) and names[service_id] not in listed:
            listed.append(names[service_id])
    return [
        AdminProfile(
            user_id=user.id,
            # As the catalog shows people, since the operator reads them the
            # way anybody browsing does.
            name=display_name(user),
            services=services.get(user.id, []),
            published_at=published_at,
        )
        for published_at, user in rows
    ]


async def _unanswered(
    session: AsyncSession, where: ColumnElement[bool]
) -> list[AdminRequest]:
    rows = await session.scalars(
        select(HelpRequest).where(where).order_by(HelpRequest.created_at).limit(LIST_CAP)
    )
    return [
        AdminRequest(id=row.id, text=row.raw_text, created_at=row.created_at)
        for row in rows
    ]


def _search_key() -> ColumnElement[Any]:
    # The same search typed twice differs in case and stray spaces; the
    # operator wants to know what people looked for, not how they typed it.
    return func.lower(func.btrim(SearchQuery.raw_text))


async def _failed_searches(
    session: AsyncSession, where: ColumnElement[bool]
) -> list[AdminSearch]:
    times = func.count(SearchQuery.id)
    last = func.max(SearchQuery.created_at)
    rows = (
        await session.execute(
            select(func.min(func.btrim(SearchQuery.raw_text)), times, last)
            .where(where)
            .group_by(_search_key())
            .order_by(times.desc(), last.desc())
            .limit(SEARCH_CAP)
        )
    ).all()
    return [AdminSearch(text=text, times=n, last_at=at) for text, n, at in rows]


async def partners(session: AsyncSession, lang: UiLang) -> list[AdminPlacement]:
    since = datetime.now(UTC) - MONTH
    recent = and_(
        PlacementEvent.placement_id == Placement.id, PlacementEvent.created_at >= since
    )
    impressions = func.count(
        case((PlacementEvent.kind == PlacementEventKind.IMPRESSION, 1))
    )
    clicks = func.count(case((PlacementEvent.kind == PlacementEventKind.CLICK, 1)))
    rows = (
        await session.execute(
            select(Placement, impressions, clicks)
            .outerjoin(PlacementEvent, recent)
            .options(
                selectinload(Placement.offer).selectinload(PartnerOffer.partner),
                selectinload(Placement.offer).selectinload(PartnerOffer.texts),
            )
            .group_by(Placement.id)
            .order_by(Placement.is_active.desc(), impressions.desc(), Placement.id)
        )
    ).all()
    return [
        AdminPlacement(
            placement_id=placement.id,
            partner=placement.offer.partner.name,
            title=text.title if (text := offer_text(placement.offer, lang)) else "",
            slot=placement.slot.value,
            is_active=placement.is_active,
            impressions=shown,
            clicks=clicked,
        )
        for placement, shown, clicked in rows
    ]
