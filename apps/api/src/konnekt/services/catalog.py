"""Assembling the screens: home, search results, one person's page."""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from konnekt.db.models import (
    AvailabilitySlot,
    HelperProfile,
    Institution,
    Offer,
    ServiceType,
    Subject,
    User,
    UserEducation,
)
from konnekt.db.models.enums import PublishStatus, UiLang
from konnekt.schemas import (
    Avatar,
    HelperCardOut,
    HelperDetailOut,
    HomeSection,
    OfferOut,
    Phrase,
    Price,
    Stat,
)

SortKey = Literal["relevance", "price", "available"]

# Tile colours on the client, in a fixed order. The server picks an index so
# the same person keeps the same colour on every screen.
TONE_COUNT = 6


def avatar_for(user: User) -> Avatar:
    initials = (user.first_name or "?")[:1].upper()
    if user.last_name:
        initials += user.last_name[:1].upper()
    return Avatar(
        id=user.id,
        initials=initials,
        tone=user.tg_id % TONE_COUNT,
        photo_url=user.photo_url,
    )


def _localised(rows, lang: UiLang, attr: str = "name") -> str | None:
    """Pick a translation, falling back to any that exists.

    A missing Ukrainian name should show the Czech one, not an empty row.
    """
    for row in rows:
        if row.lang == lang:
            value = getattr(row, attr, None)
            if value:
                return value
    for row in rows:
        value = getattr(row, attr, None)
        if value:
            return value
    return None


async def home_sections(
    session: AsyncSession, lang: UiLang
) -> tuple[list[HomeSection], list[HomeSection]]:
    """The whole home screen in one round trip.

    Counts are of *people*, not offers: a tutor who lists calculus and linear
    algebra is one person to show, and "9" under a category that has four
    tutors would be a lie the moment anyone counted the faces.
    """
    counts = {
        service_type_id: count
        for service_type_id, count in (
            await session.execute(
                select(
                    Offer.service_type_id,
                    func.count(func.distinct(Offer.helper_id)),
                )
                .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
                .where(
                    Offer.is_active.is_(True),
                    HelperProfile.status == PublishStatus.PUBLISHED,
                )
                .group_by(Offer.service_type_id)
            )
        ).all()
    }

    service_types = (
        await session.scalars(
            select(ServiceType)
            .where(ServiceType.is_active.is_(True))
            .order_by(ServiceType.sort)
            .options(selectinload(ServiceType.names))
        )
    ).all()

    avatars = await _sample_avatars(session, [st.id for st in service_types])

    people = [
        HomeSection(
            kind="service_type",
            code=st.code,
            name=_localised(st.names, lang) or st.code,
            hint=_localised(st.names, lang, "hint"),
            tone=index % TONE_COUNT,
            count=counts.get(st.id, 0),
            avatars=avatars.get(st.id, []),
        )
        for index, st in enumerate(service_types)
    ]

    # Things are not seeded yet; the section stays empty rather than absent so
    # the client layout does not change shape once it fills.
    return people, []


async def _sample_avatars(
    session: AsyncSession, service_type_ids: list[int], per_section: int = 3
) -> dict[int, list[Avatar]]:
    """Top helpers per category, for every category in one query.

    One query rather than one per category, and de-duplicated *before* the
    limit: a helper with two offers in the same category used to consume two
    of the three slots and leave the row looking half-empty.
    """
    if not service_type_ids:
        return {}

    distinct_pairs = (
        select(
            Offer.service_type_id.label("service_type_id"),
            User.id.label("user_id"),
            HelperProfile.deals_count.label("deals_count"),
        )
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .join(User, User.id == HelperProfile.user_id)
        .where(
            Offer.service_type_id.in_(service_type_ids),
            Offer.is_active.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
        )
        .distinct()
        .subquery()
    )
    ranked = (
        select(
            distinct_pairs.c.service_type_id,
            distinct_pairs.c.user_id,
            func.row_number()
            .over(
                partition_by=distinct_pairs.c.service_type_id,
                order_by=(
                    distinct_pairs.c.deals_count.desc(),
                    distinct_pairs.c.user_id,
                ),
            )
            .label("rank"),
        )
        .select_from(distinct_pairs)
        .subquery()
    )

    rows = (
        await session.execute(
            select(ranked.c.service_type_id, User)
            .join(User, User.id == ranked.c.user_id)
            .where(ranked.c.rank <= per_section)
            .order_by(ranked.c.service_type_id, ranked.c.rank)
        )
    ).all()

    out: dict[int, list[Avatar]] = {}
    for service_type_id, user in rows:
        out.setdefault(service_type_id, []).append(avatar_for(user))
    return out


def _offer_query(
    *,
    subject_id: int | None,
    institution_id: int | None,
    service_type_id: int | None,
    max_price: float | None,
    langs: list[str],
):
    stmt = (
        select(Offer)
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .where(
            Offer.is_active.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
        )
    )
    if subject_id:
        stmt = stmt.where(Offer.subject_id == subject_id)
    if service_type_id:
        stmt = stmt.where(Offer.service_type_id == service_type_id)
    if institution_id:
        # An offer with no institution is not excluded: a calculus tutor who
        # did not tie themselves to one school can still help at ČVUT. They
        # just rank lower, and the card says why.
        stmt = stmt.where(
            (Offer.institution_id == institution_id) | Offer.institution_id.is_(None)
        )
    if max_price is not None:
        stmt = stmt.where(
            (Offer.price_amount <= max_price) | Offer.price_amount.is_(None)
        )
    if langs:
        stmt = stmt.where(Offer.langs.overlap(langs))
    return stmt


def _has_free_slot():
    """Whether the helper has an availability window still ahead of them."""
    return (
        select(AvailabilitySlot.id)
        .where(
            AvailabilitySlot.helper_id == Offer.helper_id,
            func.upper(AvailabilitySlot.period) > func.now(),
        )
        .exists()
    )


async def search(
    session: AsyncSession,
    lang: UiLang,
    *,
    viewer: User,
    subject_id: int | None = None,
    institution_id: int | None = None,
    service_type_id: int | None = None,
    max_price: float | None = None,
    langs: list[str] | None = None,
    sort: SortKey = "relevance",
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[HelperCardOut]]:
    """One card per person, ordered in SQL so paging is coherent.

    Three things this has to get right, and each was wrong when it was done
    the obvious way:

    * A person appears once. Matching two of their offers is a reason to rank
      them higher, not to show them twice.
    * Ordering is total. Every sort ends in the offer id, because ties left
      to the planner's discretion make page two overlap page one.
    * Sorting and "cheapest" are computed over the whole result, not over the
      slice already in memory.
    """
    langs = langs or []
    base = _offer_query(
        subject_id=subject_id,
        institution_id=institution_id,
        service_type_id=service_type_id,
        max_price=max_price,
        langs=langs,
    )

    # with_only_columns on the base query, not a count over base.subquery():
    # the latter leaves the aggregate pointing at the outer offers table and
    # silently produces a cartesian product with the subquery.
    total = (
        await session.scalar(
            base.with_only_columns(func.count(func.distinct(Offer.helper_id)))
        )
    ) or 0
    if not total:
        return 0, []

    cheapest = await session.scalar(base.with_only_columns(func.min(Offer.price_amount)))

    # coalesce, not a bare comparison: `institution_id = :x` evaluates to NULL
    # when the offer has none, and Postgres sorts NULLs first under DESC — so
    # the offers that did *not* match were coming out above the ones that did.
    institution_hit = (
        func.coalesce(Offer.institution_id == institution_id, False).desc()
        if institution_id
        else literal(0)
    )

    # One offer per helper: the best-matching, then the cheapest, then by id.
    best_per_helper = (
        base.with_only_columns(Offer.id.label("offer_id"))
        .distinct(Offer.helper_id)
        .order_by(
            Offer.helper_id,
            institution_hit,
            Offer.price_amount.asc().nulls_last(),
            Offer.id,
        )
        .subquery()
    )

    stmt = (
        select(Offer)
        .join(best_per_helper, best_per_helper.c.offer_id == Offer.id)
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .options(
            selectinload(Offer.helper).selectinload(HelperProfile.user),
            selectinload(Offer.helper).selectinload(HelperProfile.availability),
        )
    )

    if sort == "price":
        stmt = stmt.order_by(Offer.price_amount.asc().nulls_last(), Offer.id)
    elif sort == "available":
        stmt = stmt.order_by(
            _has_free_slot().desc(),
            HelperProfile.response_minutes_avg.asc().nulls_last(),
            Offer.id,
        )
    else:
        stmt = stmt.order_by(
            institution_hit,
            HelperProfile.deals_count.desc(),
            HelperProfile.rating.desc().nulls_last(),
            Offer.id,
        )

    offers = (await session.scalars(stmt.limit(limit).offset(offset))).unique().all()

    viewer_institutions = set(
        (
            await session.scalars(
                select(UserEducation.institution_id).where(
                    UserEducation.user_id == viewer.id
                )
            )
        ).all()
    )
    if viewer.institution_id:
        viewer_institutions.add(viewer.institution_id)

    return total, [
        _to_card(
            offer,
            lang,
            requested_institution_id=institution_id,
            viewer_institutions=viewer_institutions,
            cheapest=float(cheapest) if cheapest is not None else None,
        )
        for offer in offers
    ]


def _to_card(
    offer: Offer,
    lang: UiLang,
    *,
    requested_institution_id: int | None,
    viewer_institutions: set[int],
    cheapest: float | None,
) -> HelperCardOut:
    helper = offer.helper
    user = helper.user

    return HelperCardOut(
        user_id=user.id,
        name=_display_name(user),
        avatar=avatar_for(user),
        affiliation=helper.headline,
        price=Price(
            amount=float(offer.price_amount) if offer.price_amount is not None else None,
            currency=offer.price_currency,
            unit=offer.price_unit,
        ),
        reason=_reason(
            offer,
            requested_institution_id=requested_institution_id,
            viewer_institutions=viewer_institutions,
            cheapest=cheapest,
        ),
        availability=_availability(helper),
        rating=float(helper.rating) if helper.rating is not None else None,
        deals_count=helper.deals_count,
        langs=list(offer.langs),
    )


def _display_name(user: User) -> str:
    """First name plus an initial — the convention in the mockups.

    Full surnames are neither needed to choose someone nor ours to publish.
    """
    if user.last_name:
        return f"{user.first_name} {user.last_name[:1]}."
    return user.first_name


def _reason(
    offer: Offer,
    *,
    requested_institution_id: int | None,
    viewer_institutions: set[int],
    cheapest: float | None,
) -> Phrase | None:
    """Why this person is in the list.

    Sometimes the honest answer is "they are cheap and have no experience with
    your exam". Saying that is what makes the other rows believable.
    """
    helper = offer.helper

    if requested_institution_id and offer.institution_id == requested_institution_id:
        if helper.deals_count >= 5:
            return Phrase(
                code="reason.same_exam_experience",
                params={"deals": helper.deals_count},
            )
        return Phrase(code="reason.same_institution")

    if requested_institution_id and offer.institution_id is None:
        if offer.price_amount is not None and offer.price_amount == cheapest:
            return Phrase(code="reason.cheapest_but_unproven")
        return Phrase(code="reason.subject_only")

    if offer.institution_id and offer.institution_id in viewer_institutions:
        return Phrase(code="reason.your_faculty")

    if helper.deals_count >= 5:
        return Phrase(code="reason.experience", params={"deals": helper.deals_count})
    return None


def _window(slot: AvailabilitySlot) -> tuple[datetime, datetime]:
    """The two ends of a slot, as two datetimes.

    A `tstzrange` may be unbounded, so both ends are typed as optional — but
    `availability_slots` carries a `period_is_bounded` check constraint that
    refuses such a row. This is where that database guarantee is turned back
    into something the code above can rely on, in one place rather than as a
    None check at every use.
    """
    lower, upper = slot.period.lower, slot.period.upper
    if lower is None or upper is None:  # pragma: no cover — the constraint forbids it
        raise ValueError(f"availability slot {slot.id} is unbounded")
    return lower, upper


def _upcoming(helper: HelperProfile, now: datetime) -> list[datetime]:
    """When this person is next free, earliest first."""
    starts = []
    for slot in helper.availability:
        lower, upper = _window(slot)
        if upper > now:
            starts.append(lower)
    return sorted(starts)


def _availability(helper: HelperProfile) -> Phrase | None:
    upcoming = _upcoming(helper, datetime.now(UTC))
    if upcoming:
        return Phrase(
            code="availability.free_on",
            params={"date": upcoming[0].date().isoformat()},
        )
    if helper.response_minutes_avg:
        return Phrase(
            code="availability.responds_in",
            params={"minutes": helper.response_minutes_avg},
        )
    return None


async def helper_detail(
    session: AsyncSession, user_id: int, lang: UiLang
) -> HelperDetailOut | None:
    helper = await session.scalar(
        select(HelperProfile)
        .where(HelperProfile.user_id == user_id)
        .options(
            selectinload(HelperProfile.user),
            selectinload(HelperProfile.availability),
            selectinload(HelperProfile.offers).selectinload(Offer.helper),
        )
    )
    if helper is None or helper.status != PublishStatus.PUBLISHED:
        return None

    user = helper.user
    offers = await _offers_out(session, helper, lang)

    stats: list[Stat] = []
    if helper.deals_count:
        stats.append(Stat(code="stat.deals", value=str(helper.deals_count)))
    if helper.rating is not None:
        stats.append(Stat(code="stat.rating", value=f"{float(helper.rating):.1f}"))
    if helper.published_at:
        years = (datetime.now(UTC) - helper.published_at).days // 365
        stats.append(
            Stat(code="stat.years" if years else "stat.since", value=str(years or 1))
        )

    free = _upcoming(helper, datetime.now(UTC))[:4]

    return HelperDetailOut(
        user_id=user.id,
        name=_display_name(user),
        avatar=avatar_for(user),
        affiliation=helper.headline,
        about=helper.about,
        headline=helper.headline,
        stats=stats,
        offers=offers,
        langs=sorted({lang_code for o in helper.offers for lang_code in o.langs}),
        work_format=helper.work_format,
        place_note=helper.place_note,
        free_slots=free,
        intro_context={
            "name": user.first_name,
            "subjects": ", ".join(sorted({o.subject for o in offers if o.subject})),
        },
        telegram_url=(f"https://t.me/{user.tg_username}" if user.tg_username else None),
    )


async def _offers_out(
    session: AsyncSession, helper: HelperProfile, lang: UiLang
) -> list[OfferOut]:
    if not helper.offers:
        return []

    subject_ids = {o.subject_id for o in helper.offers if o.subject_id}
    institution_ids = {o.institution_id for o in helper.offers if o.institution_id}
    service_ids = {o.service_type_id for o in helper.offers}

    subjects = {
        s.id: s
        for s in (
            await session.scalars(
                select(Subject)
                .where(Subject.id.in_(subject_ids or {0}))
                .options(selectinload(Subject.names))
            )
        ).all()
    }
    institutions = {
        i.id: i
        for i in (
            await session.scalars(
                select(Institution)
                .where(Institution.id.in_(institution_ids or {0}))
                .options(selectinload(Institution.names))
            )
        ).all()
    }
    services = {
        s.id: s
        for s in (
            await session.scalars(
                select(ServiceType)
                .where(ServiceType.id.in_(service_ids or {0}))
                .options(selectinload(ServiceType.names))
            )
        ).all()
    }

    out: list[OfferOut] = []
    for offer in helper.offers:
        if not offer.is_active:
            continue
        service = services.get(offer.service_type_id)
        subject = subjects.get(offer.subject_id) if offer.subject_id else None
        institution = (
            institutions.get(offer.institution_id) if offer.institution_id else None
        )
        out.append(
            OfferOut(
                id=offer.id,
                service_type=service.code if service else "",
                service_type_name=(_localised(service.names, lang) if service else "")
                or "",
                subject=_localised(subject.names, lang) if subject else None,
                institution=(
                    _localised(institution.names, lang, "short_name")
                    or _localised(institution.names, lang)
                    if institution
                    else None
                ),
                price=Price(
                    amount=(
                        float(offer.price_amount)
                        if offer.price_amount is not None
                        else None
                    ),
                    currency=offer.price_currency,
                    unit=offer.price_unit,
                ),
                langs=list(offer.langs),
                work_format=offer.work_format,
            )
        )
    return out


__all__ = [
    "avatar_for",
    "helper_detail",
    "home_sections",
    "search",
]
