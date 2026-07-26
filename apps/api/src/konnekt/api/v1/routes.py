from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from konnekt.api.deps import LangDep, SessionDep, UserDep
from konnekt.api.schemas import (
    Chip,
    Clarify,
    ClarifyOption,
    HelperDetailOut,
    HelperUpsert,
    HomeOut,
    InstitutionOut,
    IntroOut,
    IntroRequest,
    LanguageOut,
    MeOut,
    MeUpdate,
    ParseOut,
    ParseRequest,
    Phrase,
    PlacementOut,
    Price,
    RequestCreate,
    RequestOut,
    SearchFilters,
    SearchOut,
    ServiceTypeOut,
    SubjectOut,
)
from konnekt.db.models import (
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
    WorkFormat,
)
from konnekt.services import catalog, parser, placements
from konnekt.services.catalog import _localised, avatar_for

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
    child_counts = dict(
        (
            await session.execute(
                select(Subject.parent_id, func.count(Subject.id))
                .where(Subject.parent_id.in_([r.id for r in rows] or [0]))
                .group_by(Subject.parent_id)
            )
        ).all()
    )
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
    sort: str = Query(default="relevance", pattern="^(relevance|price|available)$"),
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
        sort=sort,  # type: ignore[arg-type]
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
    return detail


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
        helper.status = PublishStatus.PUBLISHED
        helper.published_at = helper.published_at or datetime.now(UTC)
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
async def healthz(session: SessionDep) -> dict[str, str | int]:
    await session.execute(select(1))
    uptime = datetime.now(UTC) - _STARTED_AT
    return {
        "status": "ok",
        "database": "ok",
        "uptime_seconds": int(uptime / timedelta(seconds=1)),
    }
