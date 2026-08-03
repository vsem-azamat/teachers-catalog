"""One free-text field, and what the catalog makes of it.

`parse` turns a sentence into editable chips and at most one clarifying
question; `search` runs the axes those chips describe.
"""

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from students_cz.api.deps import LangDep, SessionDep, UserDep
from students_cz.db.models import (
    Institution,
    SearchQuery,
    ServiceType,
    Subject,
)
from students_cz.db.models.enums import (
    UserEventKind,
)
from students_cz.schemas import (
    Chip,
    Clarify,
    ClarifyOption,
    ParseOut,
    ParseRequest,
    Phrase,
    SearchFilters,
    SearchOut,
)
from students_cz.services import catalog, parser
from students_cz.services.naming import short_form, translated
from students_cz.services.people import log_event

router = APIRouter()


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
                    label=translated(service, lang) or service.code,
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

    # Every parsed filter the search can apply, the budget included. Leaving one
    # out counts people this query does not reach, and writes that number into
    # `search_queries`, where a result for a query nobody ran is worse than no
    # row at all. The deadline is the exception that cannot be honoured: there is
    # no date filter to pass it to, so a query saying nothing but a date counts
    # the whole catalog — see docs/data-model.md.
    total, _ = await catalog.search(
        session,
        lang,
        viewer=user,
        subject_id=parsed.subject.id if parsed.subject else None,
        institution_id=parsed.institution.id if parsed.institution else None,
        service_type_id=service_type_id,
        max_price=parsed.budget_max,
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
                # What the embedder proposed, and whether it was believed.
                # Logged even when refused: the two thresholds it is judged by
                # were set by eye, and this is the only place the numbers to
                # replace them can come from.
                "vector": (
                    {
                        "subject_id": parsed.vector[0].id,
                        "score": round(parsed.vector[0].score, 3),
                        "lead": round(parsed.vector[1], 3),
                        "used": parsed.subject is not None
                        and parsed.subject.matched_on == "vector",
                    }
                    if parsed.vector
                    else None
                ),
            },
            results_count=total,
            parser="rules.v1",
        )
    )

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
                    label=translated(row, lang) or row.slug,
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
                    label=short_form(row, lang) or row.code,
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
                    label=translated(row, lang) or row.code,
                    value=row.id,
                )
            )
    if max_price is not None:
        chips.append(Chip(kind="budget", label=str(int(max_price)), value=int(max_price)))
    return chips
