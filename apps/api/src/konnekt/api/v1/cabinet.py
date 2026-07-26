"""A helper's own profile — reading it, and saving it.

The counterpart to `browse`: the same offers, seen from the side of the person
who owns them.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from konnekt.api.deps import LangDep, SessionDep, UserDep
from konnekt.api.schemas import (
    Chip,
    HelperUpsert,
    IntroOut,
    IntroRequest,
    MeOut,
    MyHelperOut,
    MyOfferOut,
    Price,
)
from konnekt.api.v1._shared import require_row
from konnekt.api.v1.me import read_me
from konnekt.db.models import (
    HelperProfile,
    Institution,
    Offer,
    ServiceType,
    Subject,
)
from konnekt.db.models.enums import (
    ContentLang,
    PriceUnit,
    PublishStatus,
    UserEventKind,
    WorkFormat,
)
from konnekt.services import parser
from konnekt.services.catalog import _localised
from konnekt.services.people import log_event

router = APIRouter()


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

    The set of offers is authoritative — whatever the client did not send is
    deleted, because a partial update would leave rows behind that the person
    believes they removed. The *rows*, though, are matched on their axes and
    updated in place. Deleting and reinserting was simpler and cost every past
    `contacts` row its `offer_id`, which is `ON DELETE SET NULL`: harmless when
    publishing happened once in a lifetime, and not harmless now that the
    cabinet invites someone to fix a price in ten seconds.

    Fields the payload does not carry are left alone. A profile is edited by
    more than one screen, and each of them sends what it knows about.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        helper = HelperProfile(user_id=user.id)
        session.add(helper)

    # A ban is not something the banned person can lift by pressing publish.
    if helper.status == PublishStatus.BANNED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this profile is blocked")

    # `model_fields_set` distinguishes "omitted" from "explicitly null", which
    # a plain assignment cannot: the cabinet sends no headline, and an
    # unconditional write there wiped the line under the person's name on
    # every card in the catalog the first time they changed a price.
    given = payload.model_fields_set
    if "headline" in given:
        helper.headline = payload.headline
    if "about" in given:
        helper.about = payload.about
    if "city" in given:
        helper.city = payload.city
    if "place_note" in given:
        helper.place_note = payload.place_note
    helper.raw_intro = payload.raw_intro or helper.raw_intro
    helper.about_lang = ContentLang(lang.value)
    helper.work_format = payload.work_format

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
    existing = {
        (row.service_type_id, row.subject_id, row.institution_id): row
        for row in (
            await session.scalars(select(Offer).where(Offer.helper_id == user.id))
        ).all()
    }

    seen_axes: set[tuple[int, int | None, int | None]] = set()
    for spec in payload.offers:
        if spec.service_type_id not in valid_service_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"unknown service type {spec.service_type_id}",
            )
        await require_row(session, Subject, spec.subject_id, "subject_id")
        await require_row(session, Institution, spec.institution_id, "institution_id")

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

        offer = existing.get(axes)
        if offer is None:
            offer = Offer(
                helper_id=user.id,
                service_type_id=spec.service_type_id,
                subject_id=spec.subject_id,
                institution_id=spec.institution_id,
            )
            session.add(offer)
        offer.price_amount = spec.price_amount
        offer.price_unit = spec.price_unit
        offer.langs = spec.langs or list(user.spoken_langs)
        offer.work_format = payload.work_format
        offer.is_active = True

    dropped = [row.id for axes, row in existing.items() if axes not in seen_axes]
    if dropped:
        await session.execute(delete(Offer).where(Offer.id.in_(dropped)))
    await session.commit()
    return await read_me(user, session, lang)
