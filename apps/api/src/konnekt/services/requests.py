"""Which open requests a helper is shown, and in what order.

The second-largest algorithm in the product. It is a rule about the catalog —
who may look, what counts as a match, which signal outranks which — and not a
fact about HTTP, so it lives here and the endpoint only renders what it
returns.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.db.models import (
    HelperProfile,
    HelpRequest,
    Offer,
    RequestResponse,
    User,
)
from konnekt.db.models.enums import PublishStatus, RequestStatus
from konnekt.services.errors import Forbidden


@dataclass(frozen=True, slots=True)
class FeedRow:
    """One request, its author, and which of the helper's axes it hit.

    The three flags are the contract, not the sentence built out of them: the
    line the reader sees is rendered from these, and it has to name the same
    axis that lifted the row or it reads as a non sequitur.
    """

    request: HelpRequest
    author: User
    on_subject: bool
    on_institution: bool
    on_service: bool


async def feed_for(session: AsyncSession, *, user: User, limit: int) -> list[FeedRow]:
    """Open requests, for someone who could answer them.

    Visible to any helper profile including a draft one: seeing that four
    people want help with the thing you teach is the argument for finishing
    the profile, and withholding it until published gets that backwards. What
    a draft cannot do is answer.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        raise Forbidden("only helpers can see incoming requests")
    # A ban has to cover this too. The feed carries every author's name, photo,
    # full text and budget — for someone banned for harassment it is a target
    # list, and being unable to answer in-app does not help if the reason they
    # were banned is that they contact people outside it.
    if helper.status is PublishStatus.BANNED:
        raise Forbidden("this profile is banned")

    subject_ids, institution_ids, service_ids = await _axes_of(session, user)

    subject_match = _matches(HelpRequest.subject_id, subject_ids)
    institution_match = _matches(HelpRequest.institution_id, institution_ids)
    service_match = _matches(HelpRequest.service_type_id, service_ids)

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

    return [
        FeedRow(
            request=request,
            author=author,
            on_subject=bool(on_subject),
            on_institution=bool(on_institution),
            on_service=bool(on_service),
        )
        for request, author, on_subject, on_institution, on_service in rows
    ]


async def _axes_of(
    session: AsyncSession, user: User
) -> tuple[set[int], set[int], set[int]]:
    """What this helper actually offers, as three sets of ids."""
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
    return subject_ids, institution_ids, service_ids


def _matches(column, ids: set[int]):
    """Does this request hit one of the helper's axes?

    coalesce, because `subject_id IN (...)` is NULL for a request with no
    subject, and NULL sorts *first* under DESC — which would rank every vague
    request above every matching one.

    None when the helper has nothing on that axis: the term is then a
    constant, and a constant cannot go in ORDER BY — Postgres reads a bare
    `false` there as a column ordinal and rejects it.
    """
    if not ids:
        return None
    return func.coalesce(column.in_(ids), False)
