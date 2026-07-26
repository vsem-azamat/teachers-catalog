import logging
from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, false, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from konnekt.api.deps import LangDep, SessionDep, UserDep
from konnekt.api.schemas import (
    Chip,
    Clarify,
    ClarifyOption,
    ContactOut,
    FeedRequestOut,
    HelperDetailOut,
    HelperUpsert,
    HomeOut,
    InstitutionOut,
    IntroOut,
    IntroRequest,
    LanguageOut,
    MeOut,
    MeUpdate,
    MyHelperOut,
    MyOfferOut,
    ParseOut,
    ParseRequest,
    Phrase,
    PlacementOut,
    Price,
    RequestCreate,
    RequestOut,
    ResponseCreate,
    ResponseOut,
    SearchFilters,
    SearchOut,
    ServiceTypeOut,
    SubjectOut,
)
from konnekt.bot.texts import (
    FOR_PRICE,
    NEW_RESPONSE,
    RESPONSE_ACCEPTED,
    WAIT_FOR_MESSAGE,
    WRITE_TO,
    pick,
)
from konnekt.db.models import (
    Contact,
    HelperProfile,
    HelpRequest,
    Institution,
    Language,
    Offer,
    Placement,
    RequestResponse,
    SearchQuery,
    ServiceType,
    Subject,
    User,
)
from konnekt.db.models.enums import (
    ContentLang,
    PlacementSlot,
    PriceUnit,
    PublishStatus,
    RequestStatus,
    ResponseStatus,
    UserEventKind,
    WorkFormat,
)
from konnekt.services import catalog, notify, parser, placements
from konnekt.services.catalog import _localised, avatar_for
from konnekt.services.notify import quote
from konnekt.services.people import log_event

log = logging.getLogger("konnekt")

router = APIRouter(prefix="/api/v1")


async def _require(session, model, value: int | None, field: str) -> None:
    """Reject an unknown foreign key here rather than at the database.

    Without this a typo'd id surfaces as ForeignKeyViolation — a 500 that says
    nothing useful — instead of a 422 naming the field.
    """
    if value is None:
        return
    if await session.scalar(select(model.id).where(model.id == value)) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown {field}: {value}"
        )


# ── the way in, for a browser ───────────────────────────────────────────


async def _bot_username(app) -> str | None:
    """The bot's public handle, asked for once and remembered."""
    cached = getattr(app.state, "bot_username", None)
    if cached:
        return cached
    bot = getattr(app.state, "bot", None)
    if bot is None:
        return None
    try:
        me = await bot.get_me()
    except Exception:
        log.warning("could not read the bot's own username", exc_info=True)
        return None
    app.state.bot_username = me.username
    return me.username


@router.get("/open", include_in_schema=False, tags=["public"])
async def open_in_telegram(request: Request) -> RedirectResponse:
    """Send a browser to the bot.

    Unauthenticated on purpose: this is what the landing page's button points
    at, and the landing is what someone sees who has never opened Telegram
    here. It redirects rather than returning the handle so the handle exists
    in exactly one place — the token the API is already running with. Change
    the bot and nothing in the frontend or the build needs to know.
    """
    username = await _bot_username(request.app)
    if username is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no bot is configured")
    # 302 rather than 301: a permanent redirect would be cached by the browser
    # for ever, and the target is a handle that can change.
    return RedirectResponse(f"https://t.me/{username}", status_code=302)


# ── who am I ────────────────────────────────────────────────────────────


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
            institution = _institution_out(row, lang)

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
        await _require(
            session, Institution, payload.institution_id or None, "institution_id"
        )
        user.institution_id = payload.institution_id or None
    await session.commit()
    return await read_me(user, session, payload.ui_lang or lang)


# ── home ────────────────────────────────────────────────────────────────


@router.get("/home", response_model=HomeOut, tags=["catalog"])
async def home(session: SessionDep, lang: LangDep, user: UserDep) -> HomeOut:
    people, things = await catalog.home_sections(session, lang)
    # The first screen stands in for "opened the app". Logging every request
    # would drown the signal in taxonomy fetches.
    await log_event(session, user.id, UserEventKind.APP_OPEN, lang=lang.value)
    await session.commit()
    return HomeOut(people=people, things=things)


# ── reference data ──────────────────────────────────────────────────────


@router.get(
    "/taxonomy/service-types", response_model=list[ServiceTypeOut], tags=["taxonomy"]
)
async def service_types(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[ServiceTypeOut]:
    rows = (
        await session.scalars(
            select(ServiceType)
            .where(ServiceType.is_active.is_(True))
            .order_by(ServiceType.sort)
            .options(selectinload(ServiceType.names))
        )
    ).all()
    return [
        ServiceTypeOut(
            id=r.id,
            code=r.code,
            name=_localised(r.names, lang) or r.code,
            hint=_localised(r.names, lang, "hint"),
            requires_subject=r.requires_subject,
            requires_institution=r.requires_institution,
        )
        for r in rows
    ]


@router.get("/taxonomy/subjects", response_model=list[SubjectOut], tags=["taxonomy"])
async def subjects(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    parent_id: int | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=300),
) -> list[SubjectOut]:
    """Browse the tree, or search it.

    With `q` the answer comes from fuzzy matching, so "matan" and "матан" both
    work. Without it, one level of the tree is returned.
    """
    if q:
        from konnekt.services.lookup import find_subjects

        matches = await find_subjects(session, q, lang, limit=limit, threshold=0.4)
        ids = [m.id for m in matches]
        if not ids:
            return []
        rows = {
            s.id: s
            for s in (
                await session.scalars(
                    select(Subject)
                    .where(Subject.id.in_(ids))
                    .options(selectinload(Subject.names))
                )
            ).all()
        }
        counts = await _offer_counts(session, ids)
        return [
            SubjectOut(
                id=m.id,
                slug=rows[m.id].slug,
                name=m.label,
                parent_id=rows[m.id].parent_id,
                external_code=rows[m.id].external_code,
                offers_count=counts.get(m.id, 0),
            )
            for m in matches
            if m.id in rows
        ]

    stmt = (
        select(Subject)
        .where(Subject.is_active.is_(True), Subject.parent_id == parent_id)
        .order_by(Subject.sort, Subject.id)
        .options(selectinload(Subject.names))
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    child_counts = {
        parent_id: count
        for parent_id, count in (
            await session.execute(
                select(Subject.parent_id, func.count(Subject.id))
                .where(Subject.parent_id.in_([r.id for r in rows] or [0]))
                .group_by(Subject.parent_id)
            )
        ).all()
    }
    counts = await _offer_counts(session, [r.id for r in rows])
    return [
        SubjectOut(
            id=r.id,
            slug=r.slug,
            name=_localised(r.names, lang) or r.slug,
            parent_id=r.parent_id,
            has_children=child_counts.get(r.id, 0) > 0,
            external_code=r.external_code,
            offers_count=counts.get(r.id, 0),
        )
        for r in rows
    ]


async def _offer_counts(session, subject_ids: list[int]) -> dict[int, int]:
    if not subject_ids:
        return {}
    rows = await session.execute(
        select(Offer.subject_id, func.count(Offer.id))
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .where(
            Offer.subject_id.in_(subject_ids),
            Offer.is_active.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
        )
        .group_by(Offer.subject_id)
    )
    return dict(rows.all())


@router.get(
    "/taxonomy/institutions", response_model=list[InstitutionOut], tags=["taxonomy"]
)
async def institutions(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[InstitutionOut]:
    """The whole list, universities with their faculties nested.

    A couple of hundred rows — cheaper to send once than to paginate, and the
    client can then filter without another round trip.
    """
    rows = (
        await session.scalars(
            select(Institution)
            .where(Institution.is_active.is_(True))
            .order_by(Institution.sort, Institution.id)
            .options(selectinload(Institution.names))
        )
    ).all()

    by_parent: dict[int | None, list[Institution]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)

    return [
        _institution_out(row, lang, by_parent.get(row.id, []))
        for row in by_parent.get(None, [])
    ]


def _institution_out(row: Institution, lang, children=()) -> InstitutionOut:
    return InstitutionOut(
        id=row.id,
        code=row.code,
        name=_localised(row.names, lang) or row.code,
        short_name=_localised(row.names, lang, "short_name"),
        city=row.city,
        parent_id=row.parent_id,
        faculties=[_institution_out(child, lang) for child in children],
    )


@router.get("/taxonomy/languages", response_model=list[LanguageOut], tags=["taxonomy"])
async def languages(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[LanguageOut]:
    rows = (
        await session.scalars(
            select(Language)
            .where(Language.is_active.is_(True))
            .order_by(Language.sort)
            .options(selectinload(Language.names))
        )
    ).all()
    return [
        LanguageOut(code=r.code, name=_localised(r.names, lang) or r.code) for r in rows
    ]


# ── search ──────────────────────────────────────────────────────────────


@router.post("/search/parse", response_model=ParseOut, tags=["search"])
async def parse_query(
    payload: ParseRequest, session: SessionDep, lang: LangDep, user: UserDep
) -> ParseOut:
    """Read a sentence and show back what we made of it.

    Every call is logged with its parse and result count. Queries that match
    nothing are the ranked list of what the catalog is missing, and the raw
    text next to the parse is what a better parser would be trained on.
    """
    parsed = await parser.parse(session, payload.text, lang.value)

    chips: list[Chip] = []
    if parsed.subject:
        chips.append(
            Chip(
                kind="subject",
                label=parsed.subject.label,
                value=parsed.subject.id,
                confidence=round(parsed.subject.score, 2),
            )
        )
    if parsed.institution:
        chips.append(
            Chip(
                kind="institution",
                label=parsed.institution.label,
                value=parsed.institution.id,
                confidence=round(parsed.institution.score, 2),
            )
        )
    service_type_id = None
    if parsed.service_type:
        service = await session.scalar(
            select(ServiceType)
            .where(ServiceType.code == parsed.service_type)
            .options(selectinload(ServiceType.names))
        )
        if service:
            service_type_id = service.id
            chips.append(
                Chip(
                    kind="service_type",
                    label=_localised(service.names, lang) or service.code,
                    value=service.id,
                )
            )
    if parsed.deadline:
        chips.append(
            Chip(
                kind="deadline",
                label=parsed.deadline.isoformat(),
                value=parsed.deadline.isoformat(),
            )
        )
    if parsed.budget_max:
        chips.append(
            Chip(
                kind="budget",
                label=str(int(parsed.budget_max)),
                value=int(parsed.budget_max),
            )
        )

    total, _ = await catalog.search(
        session,
        lang,
        viewer=user,
        subject_id=parsed.subject.id if parsed.subject else None,
        institution_id=parsed.institution.id if parsed.institution else None,
        service_type_id=service_type_id,
        limit=1,
    )

    await log_event(
        session, user.id, UserEventKind.SEARCH, text=payload.text, results=total
    )
    session.add(
        SearchQuery(
            user_id=user.id,
            raw_text=payload.text,
            parsed={
                "subject_id": parsed.subject.id if parsed.subject else None,
                "institution_id": (parsed.institution.id if parsed.institution else None),
                "service_type": parsed.service_type,
                "deadline": parsed.deadline.isoformat() if parsed.deadline else None,
                "budget_max": parsed.budget_max,
            },
            results_count=total,
            parser="rules.v1",
        )
    )
    await session.commit()

    return ParseOut(
        chips=chips,
        clarify=_clarify_for(parsed),
        matches=total,
        note=Phrase(code="parse.nothing_recognised") if not chips else None,
    )


def _clarify_for(parsed: parser.ParsedQuery) -> Clarify | None:
    """Ask at most one question, and only when it narrows the result.

    If the text already says which kind of help is wanted, there is nothing to
    ask; if it says nothing at all, a question about exam timing would be
    guessing at the wrong thing.
    """
    if parsed.service_type or parsed.unmatched:
        return None
    return Clarify(
        code="clarify.when",
        options=[
            ClarifyOption(code="exam_prep", tone=0),
            ClarifyOption(code="exam_live_help", tone=1),
            ClarifyOption(code="both", tone=5),
        ],
    )


@router.get("/search", response_model=SearchOut, tags=["search"])
async def search_offers(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    subject_id: int | None = None,
    institution_id: int | None = None,
    service_type_id: int | None = None,
    max_price: float | None = None,
    langs: list[str] = Query(default_factory=list),
    # The literal rather than a string with a pattern: it is the same
    # constraint, it reaches OpenAPI as an enum, and it is the type the
    # catalog's own signature already asks for.
    sort: catalog.SortKey = Query(default="relevance"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> SearchOut:
    total, results = await catalog.search(
        session,
        lang,
        viewer=user,
        subject_id=subject_id,
        institution_id=institution_id,
        service_type_id=service_type_id,
        max_price=max_price,
        langs=langs,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return SearchOut(
        total=total,
        filters=SearchFilters(
            subject_id=subject_id,
            institution_id=institution_id,
            service_type_id=service_type_id,
            max_price=max_price,
            langs=langs,
        ),
        # The same chips the parse screen showed, so the results screen can say
        # what it is filtering on without re-resolving three ids itself.
        chips=await _filter_chips(
            session,
            lang,
            subject_id=subject_id,
            institution_id=institution_id,
            service_type_id=service_type_id,
            max_price=max_price,
        ),
        results=results,
    )


async def _filter_chips(
    session,
    lang,
    *,
    subject_id: int | None,
    institution_id: int | None,
    service_type_id: int | None,
    max_price: float | None,
) -> list[Chip]:
    chips: list[Chip] = []
    if subject_id:
        row = await session.scalar(
            select(Subject)
            .where(Subject.id == subject_id)
            .options(selectinload(Subject.names))
        )
        if row:
            chips.append(
                Chip(
                    kind="subject",
                    label=_localised(row.names, lang) or row.slug,
                    value=row.id,
                )
            )
    if institution_id:
        row = await session.scalar(
            select(Institution)
            .where(Institution.id == institution_id)
            .options(selectinload(Institution.names))
        )
        if row:
            chips.append(
                Chip(
                    kind="institution",
                    label=_localised(row.names, lang, "short_name")
                    or _localised(row.names, lang)
                    or row.code,
                    value=row.id,
                )
            )
    if service_type_id:
        row = await session.scalar(
            select(ServiceType)
            .where(ServiceType.id == service_type_id)
            .options(selectinload(ServiceType.names))
        )
        if row:
            chips.append(
                Chip(
                    kind="service_type",
                    label=_localised(row.names, lang) or row.code,
                    value=row.id,
                )
            )
    if max_price is not None:
        chips.append(Chip(kind="budget", label=str(int(max_price)), value=int(max_price)))
    return chips


@router.get("/helpers/{user_id}", response_model=HelperDetailOut, tags=["catalog"])
async def helper_detail(
    user_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> HelperDetailOut:
    detail = await catalog.helper_detail(session, user_id, lang)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such published profile")
    await log_event(session, user.id, UserEventKind.HELPER_VIEW, helper_id=user_id)
    await session.commit()
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
    await session.commit()

    return ContactOut(telegram_url=f"https://t.me/{helper.user.tg_username}")


# ── becoming a helper ───────────────────────────────────────────────────


@router.post("/helper/intro", response_model=IntroOut, tags=["helper"])
async def read_intro(
    payload: IntroRequest, session: SessionDep, lang: LangDep, user: UserDep
) -> IntroOut:
    """Read a free-text introduction into a draft profile.

    Nothing is saved. The point is to show the person that they were
    understood — and to let them correct it — before anything is published.
    """
    parsed = await parser.parse_intro(session, payload.text, lang.value)

    chips = [
        Chip(
            kind="subject",
            label=match.label,
            value=match.id,
            confidence=round(match.score, 2),
        )
        for match in parsed.subjects
    ]
    if parsed.institution:
        chips.append(
            Chip(
                kind="institution",
                label=parsed.institution.label,
                value=parsed.institution.id,
                confidence=round(parsed.institution.score, 2),
            )
        )
    price = None
    if parsed.price_amount is not None:
        price = Price(
            amount=parsed.price_amount,
            unit=PriceUnit(parsed.price_unit or "hour"),
        )
        chips.append(
            Chip(
                kind="price",
                label=str(int(parsed.price_amount)),
                value=int(parsed.price_amount),
            )
        )
    if parsed.work_format:
        chips.append(
            Chip(kind="work_format", label=parsed.work_format, value=parsed.work_format)
        )

    return IntroOut(
        chips=chips,
        price=price,
        work_format=WorkFormat(parsed.work_format) if parsed.work_format else None,
        institution_id=parsed.institution.id if parsed.institution else None,
        subject_ids=[m.id for m in parsed.subjects],
        missing=parsed.missing,
    )


@router.get("/helper", response_model=MyHelperOut, tags=["helper"])
async def my_helper(session: SessionDep, lang: LangDep, user: UserDep) -> MyHelperOut:
    """Read back the caller's own profile, whatever state it is in.

    Answers with an empty shell rather than 404 when there is no profile yet:
    the screen behind this is a form, and a form that has to branch on a
    missing-resource error to decide whether to render is a form with two
    code paths where one will do.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        return MyHelperOut(exists=False)

    offers = (
        await session.scalars(
            select(Offer)
            .where(Offer.helper_id == user.id, Offer.is_active.is_(True))
            .order_by(Offer.id)
        )
    ).all()

    # Names for every axis in one round trip each, rather than per offer.
    service_names = await _names_by_id(
        session, ServiceType, [o.service_type_id for o in offers], lang
    )
    subject_names = await _names_by_id(
        session, Subject, [o.subject_id for o in offers], lang
    )
    institution_names = await _names_by_id(
        session, Institution, [o.institution_id for o in offers], lang
    )
    service_codes = {
        service_type_id: code
        for service_type_id, code in (
            await session.execute(
                select(ServiceType.id, ServiceType.code).where(
                    ServiceType.id.in_({o.service_type_id for o in offers} or {0})
                )
            )
        ).all()
    }

    return MyHelperOut(
        exists=True,
        status=helper.status.value,
        headline=helper.headline,
        about=helper.about,
        work_format=helper.work_format,
        city=helper.city,
        place_note=helper.place_note,
        offers=[
            MyOfferOut(
                service_type_id=offer.service_type_id,
                service_type=service_codes.get(offer.service_type_id, ""),
                service_type_name=service_names.get(offer.service_type_id, ""),
                subject_id=offer.subject_id,
                subject_name=subject_names.get(offer.subject_id),
                institution_id=offer.institution_id,
                institution_name=institution_names.get(offer.institution_id),
                price_amount=float(offer.price_amount)
                if offer.price_amount is not None
                else None,
                price_unit=offer.price_unit,
                langs=list(offer.langs),
            )
            for offer in offers
        ],
    )


async def _names_by_id(session, model, ids, lang) -> dict[int, str]:
    """Translated names for a set of taxonomy rows, keyed by id."""
    wanted = {value for value in ids if value is not None}
    if not wanted:
        return {}
    rows = (
        await session.scalars(
            select(model).where(model.id.in_(wanted)).options(selectinload(model.names))
        )
    ).all()
    return {row.id: _localised(row.names, lang) or "" for row in rows}


@router.put("/helper", response_model=MeOut, tags=["helper"])
async def upsert_helper(
    payload: HelperUpsert, session: SessionDep, lang: LangDep, user: UserDep
) -> MeOut:
    """Create or replace the caller's helper profile and its offers.

    Offers are replaced wholesale rather than diffed: the client always sends
    the full set it is showing, and a partial update would leave rows behind
    that the person believes they deleted.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        helper = HelperProfile(user_id=user.id)
        session.add(helper)

    # A ban is not something the banned person can lift by pressing publish.
    if helper.status == PublishStatus.BANNED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this profile is blocked")

    helper.headline = payload.headline
    helper.about = payload.about
    helper.raw_intro = payload.raw_intro or helper.raw_intro
    helper.about_lang = ContentLang(lang.value)
    helper.work_format = payload.work_format
    helper.city = payload.city
    helper.place_note = payload.place_note

    if payload.publish:
        was_published = helper.status == PublishStatus.PUBLISHED
        helper.status = PublishStatus.PUBLISHED
        helper.published_at = helper.published_at or datetime.now(UTC)
        if not was_published:
            await log_event(session, user.id, UserEventKind.PROFILE_PUBLISHED)
    else:
        # HIDDEN, not DRAFT, once it has been out: "hide me" has to actually
        # take the profile out of the catalog, and the distinction preserves
        # whether anyone has ever seen it.
        helper.status = (
            PublishStatus.HIDDEN if helper.published_at else PublishStatus.DRAFT
        )
    await session.flush()

    valid_service_ids = set(
        (await session.scalars(select(ServiceType.id).where(ServiceType.is_active))).all()
    )
    await session.execute(delete(Offer).where(Offer.helper_id == user.id))
    seen_axes: set[tuple[int, int | None, int | None]] = set()
    for spec in payload.offers:
        if spec.service_type_id not in valid_service_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"unknown service type {spec.service_type_id}",
            )
        await _require(session, Subject, spec.subject_id, "subject_id")
        await _require(session, Institution, spec.institution_id, "institution_id")

        axes = (spec.service_type_id, spec.subject_id, spec.institution_id)
        if axes in seen_axes:
            # The same three axes twice violates uq_offers_axes. Saying which
            # entry is duplicated beats a unique-violation traceback.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"duplicate offer for service {axes[0]}, subject {axes[1]}, "
                f"institution {axes[2]}",
            )
        seen_axes.add(axes)
        session.add(
            Offer(
                helper_id=user.id,
                service_type_id=spec.service_type_id,
                subject_id=spec.subject_id,
                institution_id=spec.institution_id,
                price_amount=spec.price_amount,
                price_unit=spec.price_unit,
                langs=spec.langs or list(user.spoken_langs),
                work_format=payload.work_format,
            )
        )
    await session.commit()
    return await read_me(user, session, lang)


# ── requests: the catalog in reverse ────────────────────────────────────


@router.post(
    "/requests",
    response_model=RequestOut,
    status_code=status.HTTP_201_CREATED,
    tags=["requests"],
)
async def create_request(
    payload: RequestCreate, session: SessionDep, lang: LangDep, user: UserDep
) -> RequestOut:
    """Post "I need help with X" and let helpers answer.

    Anything the caller did not fill in is read out of the text, so the form
    can be a single field. A request without a deadline expires in thirty
    days; with one, the day after — an exam on the 14th is worthless on the
    15th, and a stale board is worse than an empty one.
    """
    await _require(session, Subject, payload.subject_id, "subject_id")
    await _require(session, Institution, payload.institution_id, "institution_id")
    await _require(session, ServiceType, payload.service_type_id, "service_type_id")

    parsed = await parser.parse(session, payload.text, lang.value)

    subject_id = payload.subject_id or (parsed.subject.id if parsed.subject else None)
    institution_id = payload.institution_id or (
        parsed.institution.id if parsed.institution else None
    )
    service_type_id = payload.service_type_id
    if service_type_id is None and parsed.service_type:
        service_type_id = await session.scalar(
            select(ServiceType.id).where(ServiceType.code == parsed.service_type)
        )
    deadline = payload.deadline_on or parsed.deadline

    expires_at = (
        datetime.combine(deadline, time.max, tzinfo=UTC)
        if deadline
        else datetime.now(UTC) + timedelta(days=30)
    )

    request = HelpRequest(
        author_id=user.id,
        raw_text=payload.text,
        lang=ContentLang(lang.value),
        subject_id=subject_id,
        institution_id=institution_id,
        service_type_id=service_type_id,
        deadline_on=deadline,
        budget_max=payload.budget_max or parsed.budget_max,
        langs=payload.langs or list(user.spoken_langs),
        status=RequestStatus.OPEN,
        expires_at=expires_at,
    )
    session.add(request)
    await log_event(
        session,
        user.id,
        UserEventKind.REQUEST_CREATED,
        subject_id=subject_id,
        institution_id=institution_id,
    )
    await session.commit()
    await session.refresh(request)
    return await _request_out(session, request, lang)


@router.get("/requests", response_model=list[RequestOut], tags=["requests"])
async def my_requests(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[RequestOut]:
    rows = (
        await session.scalars(
            select(HelpRequest)
            .where(HelpRequest.author_id == user.id)
            # id as a tiebreaker: created_at comes from now(), which is the
            # transaction's clock, so two rows written together share it.
            .order_by(HelpRequest.created_at.desc(), HelpRequest.id.desc())
            .limit(50)
        )
    ).all()
    return await _requests_out(session, list(rows), lang)


@router.get("/requests/feed", response_model=list[FeedRequestOut], tags=["requests"])
async def request_feed(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    limit: int = Query(20, ge=1, le=50),
) -> list[FeedRequestOut]:
    """Open requests, for someone who could answer them.

    Visible to any helper profile including a draft one: seeing that four
    people want help with the thing you teach is the argument for finishing
    the profile, and withholding it until published gets that backwards. What
    a draft cannot do is answer — see `respond_to_request`.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only helpers can see incoming requests"
        )
    # A ban has to cover this too. The feed carries every author's name, photo,
    # full text and budget — for someone banned for harassment it is a target
    # list, and being unable to answer in-app does not help if the reason they
    # were banned is that they contact people outside it.
    if helper.status is PublishStatus.BANNED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this profile is banned")

    axes = (
        await session.execute(
            select(Offer.subject_id, Offer.institution_id, Offer.service_type_id).where(
                Offer.helper_id == user.id, Offer.is_active.is_(True)
            )
        )
    ).all()
    subject_ids = {row[0] for row in axes if row[0]}
    institution_ids = {row[1] for row in axes if row[1]}
    service_ids = {row[2] for row in axes if row[2]}
    # Their own faculty counts too — a request from your own school is
    # relevant whether or not you have listed an offer against it.
    if user.institution_id:
        institution_ids.add(user.institution_id)

    def matches(column, ids: set[int]):
        """Does this request hit one of the helper's axes?

        coalesce, because `subject_id IN (...)` is NULL for a request with no
        subject, and NULL sorts *first* under DESC — which would rank every
        vague request above every matching one.

        None when the helper has nothing on that axis: the term is then a
        constant, and a constant cannot go in ORDER BY — Postgres reads a bare
        `false` there as a column ordinal and rejects it.
        """
        if not ids:
            return None
        return func.coalesce(column.in_(ids), False)

    subject_match = matches(HelpRequest.subject_id, subject_ids)
    institution_match = matches(HelpRequest.institution_id, institution_ids)
    service_match = matches(HelpRequest.service_type_id, service_ids)

    # Strongest signal first. Anything the helper has no axis for is dropped
    # rather than ordered by, since it would sort every row identically.
    ranking = [
        term.desc()
        for term in (subject_match, service_match, institution_match)
        if term is not None
    ]

    now = datetime.now(UTC)
    answered = (
        select(RequestResponse.id)
        .where(
            RequestResponse.request_id == HelpRequest.id,
            RequestResponse.helper_id == user.id,
        )
        .exists()
    )

    rows = (
        await session.execute(
            select(
                HelpRequest,
                User,
                subject_match if subject_match is not None else false(),
                institution_match if institution_match is not None else false(),
                service_match if service_match is not None else false(),
            )
            .join(User, User.id == HelpRequest.author_id)
            .where(
                HelpRequest.status == RequestStatus.OPEN,
                # Answering your own request is not a thing.
                HelpRequest.author_id != user.id,
                or_(HelpRequest.expires_at.is_(None), HelpRequest.expires_at > now),
                ~answered,
            )
            .order_by(
                *ranking,
                HelpRequest.created_at.desc(),
                # Total, so paging is stable: created_at is the transaction
                # clock and rows written together share it.
                HelpRequest.id.desc(),
            )
            .limit(limit)
        )
    ).all()

    requests = [row[0] for row in rows]
    rendered = await _requests_out(session, requests, lang)
    subjects_by_id = {r.id: r.subject for r in rendered}

    out: list[FeedRequestOut] = []
    for base, (request, author, on_subject, on_institution, on_service) in zip(
        rendered, rows, strict=True
    ):
        out.append(
            FeedRequestOut(
                # Only the shared fields. `responses_count` and `responders`
                # are not on FeedRequestOut at all — see the schema.
                **base.model_dump(exclude={"responders", "responses_count"}),
                author=avatar_for(author),
                author_name=author.first_name,
                budget=(
                    Price(
                        amount=float(request.budget_max),
                        currency=request.budget_currency,
                        unit=request.budget_unit or PriceUnit.HOUR,
                    )
                    if request.budget_max is not None
                    else None
                ),
                langs=list(request.langs),
                reason=_feed_reason(
                    on_subject=bool(on_subject),
                    on_institution=bool(on_institution),
                    on_service=bool(on_service),
                    subject=subjects_by_id.get(request.id),
                ),
            )
        )
    return out


def _feed_reason(
    *, on_subject: bool, on_institution: bool, on_service: bool, subject: str | None
) -> Phrase | None:
    """Why this request is in the list.

    One line, strongest first — and in the *same* order the ranking uses, or
    the line names a weaker axis than the one that actually lifted the row and
    reads as a non sequitur next to its neighbours.
    """
    if on_subject and subject:
        return Phrase(code="feed.same_subject", params={"subject": subject})
    if on_service:
        return Phrase(code="feed.same_service")
    if on_institution:
        return Phrase(code="feed.same_institution")
    return None


@router.post(
    "/requests/{request_id}/respond",
    response_model=ResponseOut,
    status_code=status.HTTP_201_CREATED,
    tags=["requests"],
)
async def respond_to_request(
    request_id: int,
    payload: ResponseCreate,
    background: BackgroundTasks,
    http: Request,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
) -> ResponseOut:
    """Answer someone's request.

    Published profiles only, unlike the feed: an answer is an invitation to
    look at a profile, and a draft is not there to be looked at.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None or helper.status is not PublishStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "publish your profile before answering requests"
        )
    # The same rule `start_contact` enforces, for the same reason: we do not
    # host the conversation, so a public username is the only way the author
    # can answer back. Without it an accepted answer is a dead end — both
    # sides told a deal happened and neither able to reach the other.
    if not user.tg_username:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "set a public @username in Telegram so people can write back",
        )

    request = await session.get(HelpRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such request")
    if request.author_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "this is your own request")
    expired = request.expires_at is not None and request.expires_at <= datetime.now(UTC)
    if request.status is not RequestStatus.OPEN or expired:
        raise HTTPException(status.HTTP_409_CONFLICT, "this request is closed")

    # ON CONFLICT rather than a select first: two taps on a slow connection
    # are two concurrent inserts, and the unique constraint would surface the
    # second as a 500 instead of "you already answered this".
    inserted = await session.scalar(
        pg_insert(RequestResponse)
        .values(
            request_id=request.id,
            helper_id=user.id,
            message=payload.message.strip(),
            price_amount=payload.price_amount,
            price_unit=payload.price_unit,
        )
        .on_conflict_do_nothing(constraint="uq_request_responses_pair")
        .returning(RequestResponse)
    )
    if inserted is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "you have already answered this request"
        )

    await log_event(
        session,
        user.id,
        UserEventKind.REQUEST_RESPONDED,
        request_id=request.id,
        subject_id=request.subject_id,
    )
    await session.commit()

    author = await session.get(User, request.author_id)
    [rendered] = await _responses_out(session, [inserted], lang)
    if author is not None:
        _queue_notification(
            background,
            http,
            recipient=author,
            text=pick(NEW_RESPONSE, author.ui_lang).format(
                topic=quote(_topic_of(rendered_request=request), 120),
                helper=quote(rendered.name, 64),
                price=(
                    pick(FOR_PRICE, author.ui_lang).format(
                        price=quote(_price_line(rendered.price), 40)
                    )
                    if rendered.price and rendered.price.amount is not None
                    else ""
                ),
                message=quote(inserted.message),
            ),
        )
    return rendered


@router.get(
    "/requests/{request_id}/responses",
    response_model=list[ResponseOut],
    tags=["requests"],
)
async def request_responses(
    request_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> list[ResponseOut]:
    """Who answered. The author only — this is not a public bid list."""
    request = await session.get(HelpRequest, request_id)
    if request is None or request.author_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such request")

    rows = (
        await session.scalars(
            select(RequestResponse)
            .where(RequestResponse.request_id == request.id)
            .order_by(RequestResponse.created_at.asc(), RequestResponse.id.asc())
        )
    ).all()

    # Rendered *before* marking anything, so this response still carries the
    # statuses the author has not seen yet — otherwise the client never gets a
    # chance to badge the new ones, because they arrive already read.
    out = await _responses_out(session, list(rows), lang)

    # Only the ones still unread, so an accepted or declined answer is not
    # quietly walked backwards to "read".
    for row in rows:
        if row.status is ResponseStatus.SENT:
            row.status = ResponseStatus.READ
    await session.commit()

    return out


@router.post(
    "/responses/{response_id}/accept",
    response_model=ResponseOut,
    tags=["requests"],
)
async def accept_response(
    response_id: int,
    background: BackgroundTasks,
    http: Request,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
) -> ResponseOut:
    """Pick someone.

    Does not close the request: needing two people for two subjects is
    ordinary, and closing on the first acceptance would make the common case
    the destructive one.
    """
    response, request = await _own_response(session, response_id, user)

    # Idempotent. A double tap, or a retry after a dropped response, would
    # otherwise write a second `contacts` row — which is the basis for deal
    # counts and response times — and send the helper a second "you were
    # picked". `contacts` has no unique index to catch it, and should not:
    # contacting the same person twice about two different requests is real.
    if response.status is ResponseStatus.ACCEPTED:
        [out] = await _responses_out(session, [response], lang)
        return out

    response.status = ResponseStatus.ACCEPTED

    # The same row the catalog writes when someone taps "write" on a profile,
    # so response times and deal counts count both routes to a conversation.
    session.add(
        Contact(
            student_id=user.id,
            helper_id=response.helper_id,
            request_id=request.id,
        )
    )
    await log_event(
        session,
        user.id,
        UserEventKind.RESPONSE_ACCEPTED,
        request_id=request.id,
        helper_id=response.helper_id,
    )
    await session.commit()

    helper_user = await session.get(User, response.helper_id)
    if helper_user is not None:
        _queue_notification(
            background,
            http,
            recipient=helper_user,
            text=pick(RESPONSE_ACCEPTED, helper_user.ui_lang).format(
                topic=quote(_topic_of(rendered_request=request), 120),
                student=quote(user.first_name, 64),
                contact=(
                    pick(WRITE_TO, helper_user.ui_lang).format(
                        username=quote(user.tg_username, 64)
                    )
                    if user.tg_username
                    else pick(WAIT_FOR_MESSAGE, helper_user.ui_lang)
                ),
            ),
        )

    [out] = await _responses_out(session, [response], lang)
    return out


@router.post(
    "/responses/{response_id}/decline",
    response_model=ResponseOut,
    tags=["requests"],
)
async def decline_response(
    response_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> ResponseOut:
    """Turn one down. Deliberately silent — nobody needs a rejection push."""
    response, _ = await _own_response(session, response_id, user)

    # An accepted answer cannot be walked back here. The helper has already
    # been told they were picked and a `contacts` row exists; flipping the
    # status would leave the author reading "you declined" while the other
    # side reads "you were chosen", with a recorded deal between them.
    if response.status is ResponseStatus.ACCEPTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "you already chose this person")

    response.status = ResponseStatus.DECLINED
    await session.commit()
    [out] = await _responses_out(session, [response], lang)
    return out


async def _own_response(
    session, response_id: int, user: User
) -> tuple[RequestResponse, HelpRequest]:
    """Load a response the caller is entitled to act on.

    404 rather than 403 for someone else's: whether a given id exists is not
    something a stranger should be able to probe.
    """
    response = await session.get(RequestResponse, response_id)
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such response")
    request = await session.get(HelpRequest, response.request_id)
    if request is None or request.author_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such response")
    return response, request


def _topic_of(*, rendered_request: HelpRequest) -> str:
    """A one-line handle on a request, for a notification.

    The text the person typed, not our parse of it — they recognise their own
    words, and "Mathematical Analysis I · ČVUT" is our vocabulary, not theirs.
    """
    return rendered_request.raw_text


def _price_line(price: Price | None) -> str:
    if price is None or price.amount is None:
        return ""
    amount = int(price.amount) if float(price.amount).is_integer() else price.amount
    return f"{amount} {price.currency}"


def _queue_notification(
    background: BackgroundTasks, http: Request, *, recipient: User, text: str
) -> None:
    """Send after the response goes out, not before.

    Telegram is a network call to a third party in the middle of a request the
    user is waiting on. The action is already committed; the message can take
    its time.
    """
    # `bot_started_at`, not only `bot_can_message`: the latter defaults to true
    # for every row including someone who reached the app through a direct link
    # and never messaged the bot. Telegram answers that send with a 403, which
    # `tell` reads as "blocked" — so the notification is lost *and* the person
    # is recorded as having blocked a bot they never met.
    #
    # `unsubscribed_at` is deliberately not consulted. /stop opts out of us
    # writing unprompted; this is the answer to something they set in motion.
    if recipient.bot_started_at is None or not recipient.bot_can_message:
        return
    # getattr, because app.state is populated by the lifespan hook and nothing
    # here should turn "the app was mounted without one" into a 500 on an
    # action that has already succeeded.
    bot = getattr(http.app.state, "bot", None)
    if bot is None:
        return
    settings = getattr(http.app.state, "settings", None)
    background.add_task(
        notify.tell,
        bot,
        tg_id=recipient.tg_id,
        text=text,
        lang=recipient.ui_lang,
        app_url=(settings.public_base_url or None) if settings else None,
    )


async def _responses_out(
    session, responses: list[RequestResponse], lang
) -> list[ResponseOut]:
    """Render answers with their authors, in a fixed number of queries."""
    if not responses:
        return []

    helper_ids = {r.helper_id for r in responses}
    rows = (
        await session.execute(
            select(User, HelperProfile)
            .join(HelperProfile, HelperProfile.user_id == User.id)
            .where(User.id.in_(helper_ids))
        )
    ).all()
    people = {user.id: (user, profile) for user, profile in rows}

    out = []
    for response in responses:
        found = people.get(response.helper_id)
        if found is None:
            # The profile was deleted between answering and reading. The row
            # survives by foreign key, but there is nobody left to show.
            continue
        person, profile = found
        out.append(
            ResponseOut(
                id=response.id,
                request_id=response.request_id,
                helper_id=response.helper_id,
                name=" ".join(filter(None, (person.first_name, person.last_name))),
                avatar=avatar_for(person),
                username=person.tg_username,
                affiliation=profile.headline,
                rating=float(profile.rating) if profile.rating is not None else None,
                deals_count=profile.deals_count,
                message=response.message,
                price=(
                    Price(
                        amount=float(response.price_amount),
                        currency=response.price_currency,
                        unit=response.price_unit or PriceUnit.HOUR,
                    )
                    if response.price_amount is not None
                    else None
                ),
                status=response.status.value,
                created_at=response.created_at,
            )
        )
    return out


@router.post(
    "/requests/{request_id}/close",
    response_model=RequestOut,
    tags=["requests"],
)
async def close_request(
    request_id: int, session: SessionDep, lang: LangDep, user: UserDep
) -> RequestOut:
    request = await session.get(HelpRequest, request_id)
    if request is None or request.author_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such request")
    request.status = RequestStatus.CLOSED
    await session.commit()
    return await _request_out(session, request, lang)


async def _request_out(session, request: HelpRequest, lang) -> RequestOut:
    [out] = await _requests_out(session, [request], lang)
    return out


async def _requests_out(session, requests: list[HelpRequest], lang) -> list[RequestOut]:
    """Render a whole page of requests in a fixed number of queries.

    Done per request this was five round trips each — 250 for a full page —
    and every one of them was fetching the same handful of subject and
    faculty names over and over.
    """
    if not requests:
        return []

    async def names_by_id(model, ids: set[int]) -> dict:
        if not ids:
            return {}
        rows = (
            await session.scalars(
                select(model).where(model.id.in_(ids)).options(selectinload(model.names))
            )
        ).all()
        return {row.id: row for row in rows}

    subjects = await names_by_id(
        Subject, {r.subject_id for r in requests if r.subject_id}
    )
    institutions = await names_by_id(
        Institution, {r.institution_id for r in requests if r.institution_id}
    )
    services = await names_by_id(
        ServiceType, {r.service_type_id for r in requests if r.service_type_id}
    )

    request_ids = [r.id for r in requests]
    counts = dict(
        (
            await session.execute(
                select(RequestResponse.request_id, func.count(RequestResponse.id))
                .where(RequestResponse.request_id.in_(request_ids))
                .group_by(RequestResponse.request_id)
            )
        ).all()
    )
    responder_rows = (
        await session.execute(
            select(RequestResponse.request_id, User)
            .join(User, User.id == RequestResponse.helper_id)
            .where(RequestResponse.request_id.in_(request_ids))
            .order_by(RequestResponse.request_id, RequestResponse.id)
        )
    ).all()
    responders: dict[int, list] = {}
    for request_id, responder in responder_rows:
        bucket = responders.setdefault(request_id, [])
        if len(bucket) < 4:
            bucket.append(avatar_for(responder))

    out = []
    for request in requests:
        subject = subjects.get(request.subject_id)
        institution = institutions.get(request.institution_id)
        service = services.get(request.service_type_id)
        out.append(
            RequestOut(
                id=request.id,
                text=request.raw_text,
                subject=_localised(subject.names, lang) if subject else None,
                institution=(
                    _localised(institution.names, lang, "short_name")
                    or _localised(institution.names, lang)
                    if institution
                    else None
                ),
                service_type=_localised(service.names, lang) if service else None,
                deadline_on=request.deadline_on,
                status=request.status.value,
                responses_count=counts.get(request.id, 0),
                responders=responders.get(request.id, []),
                created_at=request.created_at,
            )
        )
    return out


# ── partner placements ──────────────────────────────────────────────────


@router.get("/placements", response_model=list[PlacementOut], tags=["partners"])
async def placements_for_slot(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    slot: PlacementSlot,
    service_type: str | None = None,
    subject_id: int | None = None,
) -> list[PlacementOut]:
    return await placements.for_slot(
        session,
        lang=lang,
        slot=slot,
        context={
            "service_type": service_type,
            "subject_id": subject_id,
            "ui_lang": user.ui_lang.value,
            "month": datetime.now(UTC).month,
            # Impressions are worth nothing without knowing who saw them.
            "user_id": user.id,
        },
    )


@router.post(
    "/placements/{placement_id}/click",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["partners"],
)
async def register_click(placement_id: int, session: SessionDep, user: UserDep) -> None:
    """Record that a partner block was followed.

    The id is checked first: the partner is billed per click, so an unknown one
    must be a 404 rather than a foreign-key traceback.
    """
    exists = await session.scalar(
        select(Placement.id).where(Placement.id == placement_id)
    )
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such placement")
    await placements.record(session, placement_id, user.id, kind="click")


# ── health ──────────────────────────────────────────────────────────────

_STARTED_AT = datetime.now(UTC)

health_router = APIRouter(tags=["ops"])


@health_router.get("/healthz")
async def healthz(request: Request, session: SessionDep) -> dict[str, str | int]:
    """Liveness plus the two things that fail independently.

    A webhook that never registered leaves the catalog perfectly usable and the
    bot deaf, which is exactly the kind of half-failure nobody notices. It is
    reported here rather than folded into the status, because taking the whole
    service out of rotation over it would be worse.
    """
    await session.execute(select(1))
    uptime = datetime.now(UTC) - _STARTED_AT
    return {
        "status": "ok",
        "database": "ok",
        "webhook": getattr(request.app.state, "webhook_status", "unknown"),
        "uptime_seconds": int(uptime / timedelta(seconds=1)),
    }
