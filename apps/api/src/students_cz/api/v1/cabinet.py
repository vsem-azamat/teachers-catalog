"""A helper's own profile — reading it, and saving it.

The counterpart to `browse`: the same offers, seen from the side of the person
who owns them.
"""

from fastapi import APIRouter
from sqlalchemy import select

from students_cz.api.deps import LangDep, SessionDep, UserDep
from students_cz.api.v1.me import read_me
from students_cz.db.models import (
    HelperProfile,
    Institution,
    Offer,
    ServiceType,
    Subject,
)
from students_cz.db.models.enums import (
    PriceUnit,
    WorkFormat,
)
from students_cz.schemas import (
    Chip,
    HelperUpsert,
    IntroOut,
    IntroRequest,
    MeOut,
    MyHelperOut,
    MyOfferOut,
    Price,
)
from students_cz.services import helpers, parser
from students_cz.services.naming import names_by_id

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
    service_names = await names_by_id(
        session, ServiceType, [o.service_type_id for o in offers], lang
    )
    subject_names = await names_by_id(
        session, Subject, [o.subject_id for o in offers], lang
    )
    institution_names = await names_by_id(
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


@router.put("/helper", response_model=MeOut, tags=["helper"])
async def upsert_helper(
    payload: HelperUpsert, session: SessionDep, lang: LangDep, user: UserDep
) -> MeOut:
    """Create or replace the caller's helper profile and its offers."""
    await helpers.save_profile(session, user=user, spec=payload, lang=lang)
    return await read_me(user, session, lang)
