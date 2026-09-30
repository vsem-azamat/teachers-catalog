"""What the operator reads in the console. Reads only.

See docs/architecture.md, «The operator reads, and only reads».
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, exists, func, select
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
from students_cz.services.naming import names_by_id
from students_cz.services.people import full_name

WEEK = timedelta(days=7)
MONTH = timedelta(days=30)
# Enough to read on a phone; the counts say how long the full lists are.
LIST_CAP = 50
SEARCH_CAP = 20


async def catalog(session: AsyncSession, lang: UiLang) -> AdminCatalog:
    now = datetime.now(UTC)
    profiles = await _new_profiles(session, lang, since=now - WEEK)
    unanswered = await _unanswered(session)
    requests_week = await session.scalar(
        select(func.count(HelpRequest.id)).where(
            HelpRequest.status != RequestStatus.DRAFT,
            HelpRequest.created_at >= now - WEEK,
        )
    )
    return AdminCatalog(
        profiles=profiles[:LIST_CAP],
        unanswered=unanswered[:LIST_CAP],
        failed_searches=await _failed_searches(session, since=now - MONTH),
        counts=AdminCounts(
            profiles_week=len(profiles),
            requests_week=requests_week or 0,
            unanswered=len(unanswered),
        ),
    )


async def _new_profiles(
    session: AsyncSession, lang: UiLang, *, since: datetime
) -> list[AdminProfile]:
    rows = (
        await session.execute(
            select(HelperProfile.published_at, User)
            .join(User, User.id == HelperProfile.user_id)
            .where(
                HelperProfile.status == PublishStatus.PUBLISHED,
                HelperProfile.published_at >= since,
            )
            .order_by(HelperProfile.published_at.desc())
        )
    ).all()
    ids = [user.id for _, user in rows]
    offered = (
        await session.execute(
            select(Offer.helper_id, Offer.service_type_id)
            .where(Offer.helper_id.in_(ids))
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
            name=full_name(user),
            services=services.get(user.id, []),
            published_at=published_at,
        )
        for published_at, user in rows
    ]


async def _unanswered(session: AsyncSession) -> list[AdminRequest]:
    answered = exists().where(RequestResponse.request_id == HelpRequest.id)
    rows = await session.scalars(
        select(HelpRequest)
        .where(HelpRequest.status == RequestStatus.OPEN, ~answered)
        .order_by(HelpRequest.created_at)
    )
    return [
        AdminRequest(id=row.id, text=row.raw_text, created_at=row.created_at)
        for row in rows
    ]


async def _failed_searches(
    session: AsyncSession, *, since: datetime
) -> list[AdminSearch]:
    # The same search typed twice differs in case and stray spaces; the
    # operator wants to know what people looked for, not how they typed it.
    key = func.lower(func.btrim(SearchQuery.raw_text))
    rows = (
        await session.execute(
            select(
                func.min(func.btrim(SearchQuery.raw_text)),
                func.count(SearchQuery.id),
                func.max(SearchQuery.created_at),
            )
            .where(SearchQuery.results_count == 0, SearchQuery.created_at >= since)
            .group_by(key)
            .order_by(
                func.count(SearchQuery.id).desc(), func.max(SearchQuery.created_at).desc()
            )
            .limit(SEARCH_CAP)
        )
    ).all()
    return [
        AdminSearch(text=text, times=times, last_at=last) for text, times, last in rows
    ]


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
            title=_title(placement.offer, lang),
            slot=placement.slot.value,
            is_active=placement.is_active,
            impressions=shown,
            clicks=clicked,
        )
        for placement, shown, clicked in rows
    ]


def _title(offer: PartnerOffer, lang: UiLang) -> str:
    """The offer's title in the reader's language, else any it has."""
    texts = {text.lang: text.title for text in offer.texts}
    return texts.get(lang) or next(iter(texts.values()), "")
