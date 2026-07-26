"""The catalog in reverse: a student posts, helpers answer.

The largest domain here, because a request has a life — posted, seen, answered,
accepted, closed — and every step of it notifies somebody.
"""

from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from sqlalchemy import false, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from konnekt.api.deps import LangDep, SessionDep, UserDep
from konnekt.api.schemas import (
    FeedRequestOut,
    Phrase,
    Price,
    RequestCreate,
    RequestOut,
    ResponseCreate,
    ResponseOut,
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
    Offer,
    RequestResponse,
    ServiceType,
    Subject,
    User,
)
from konnekt.db.models.enums import (
    ContentLang,
    PriceUnit,
    PublishStatus,
    RequestStatus,
    ResponseStatus,
    UserEventKind,
)
from konnekt.services import notify, parser
from konnekt.services.catalog import _localised, avatar_for
from konnekt.services.notify import quote
from konnekt.services.people import log_event
from konnekt.services.refs import require_row

router = APIRouter()


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
    await require_row(session, Subject, payload.subject_id, "subject_id")
    await require_row(session, Institution, payload.institution_id, "institution_id")
    await require_row(session, ServiceType, payload.service_type_id, "service_type_id")

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
    # flush, not commit: the row has to exist for `refresh` to read the
    # defaults the database fills in, but the transaction belongs to the
    # request and ends when the request does.
    await session.flush()
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
