"""A helper's own profile: the publish state machine and the offer diff.

The riskiest write in the application, which is why it lives here rather than
in a request handler. Everything it enforces is a rule about the catalog, not
about HTTP, so the bot could offer the same thing tomorrow without any of it
being reimplemented.
"""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import (
    HelperProfile,
    Institution,
    Offer,
    ServiceOption,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import (
    ContentLang,
    PublishStatus,
    UiLang,
    UserEventKind,
)
from students_cz.schemas import HelperUpsert
from students_cz.services.errors import Forbidden, Invalid
from students_cz.services.people import log_event
from students_cz.services.refs import require_row


async def save_profile(
    session: AsyncSession, *, user: User, spec: HelperUpsert, lang: UiLang
) -> HelperProfile:
    """Create or replace the caller's helper profile and its offers.

    The set of offers is authoritative — whatever the caller did not send is
    deleted, because a partial update would leave rows behind that the person
    believes they removed. The *rows*, though, are matched on their axes and
    updated in place. Deleting and reinserting was simpler and cost every past
    `contacts` row its `offer_id`, which is `ON DELETE SET NULL`: harmless when
    publishing happened once in a lifetime, and not harmless now that the
    cabinet invites someone to fix a price in ten seconds.

    Fields the caller does not carry are left alone — every one of them, checked
    through `model_fields_set` rather than by testing for `None`, because a
    field with a default cannot tell the two apart otherwise. A profile is
    edited by more than one screen, and each sends only what it knows about.

    Does not commit: the caller owns the transaction.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        helper = HelperProfile(user_id=user.id)
        session.add(helper)

    # A ban is not something the banned person can lift by pressing publish.
    if helper.status == PublishStatus.BANNED:
        raise Forbidden("this profile is blocked")

    _apply_text(helper, spec, lang)
    await _apply_status(session, helper, user, publish=spec.publish)
    await session.flush()
    # Same rule as the text fields, and for the same reason. `offers` defaults
    # to an empty list, so an unconditional call here deletes everything the
    # person offers the moment a screen sends anything else on its own — which
    # is the promise the docstring above already makes.
    if "offers" in spec.model_fields_set:
        await _apply_offers(session, user=user, helper=helper, spec=spec)
    return helper


def _apply_text(helper: HelperProfile, spec: HelperUpsert, lang: UiLang) -> None:
    """Write only what the caller actually sent.

    `model_fields_set` distinguishes "omitted" from "explicitly null", which a
    plain assignment cannot: the cabinet sends no headline, and an
    unconditional write there wiped the line under the person's name on every
    card in the catalog the first time they changed a price.
    """
    given = spec.model_fields_set
    if "headline" in given:
        helper.headline = spec.headline
    if "about" in given:
        helper.about = spec.about
    if "city" in given:
        helper.city = spec.city
    if "place_note" in given:
        helper.place_note = spec.place_note
    helper.raw_intro = spec.raw_intro or helper.raw_intro
    helper.about_lang = ContentLang(lang.value)
    # `work_format` has a default of `both`, so writing it unconditionally
    # moved an online-only tutor to "either way" the moment any screen saved
    # anything else — and `_apply_offers` copies it onto every offer, so the
    # change reached each of their rows too.
    if "work_format" in given:
        helper.work_format = spec.work_format


async def _apply_status(
    session: AsyncSession, helper: HelperProfile, user: User, *, publish: bool
) -> None:
    if publish:
        was_published = helper.status == PublishStatus.PUBLISHED
        helper.status = PublishStatus.PUBLISHED
        helper.published_at = helper.published_at or datetime.now(UTC)
        if not was_published:
            await log_event(session, user.id, UserEventKind.PROFILE_PUBLISHED)
        return

    # HIDDEN, not DRAFT, once it has been out: "hide me" has to actually take
    # the profile out of the catalog, and the distinction preserves whether
    # anyone has ever seen it.
    helper.status = PublishStatus.HIDDEN if helper.published_at else PublishStatus.DRAFT


async def _apply_offers(
    session: AsyncSession, *, user: User, helper: HelperProfile, spec: HelperUpsert
) -> None:
    existing = {
        (row.service_type_id, row.subject_id, row.institution_id): row
        for row in (
            await session.scalars(select(Offer).where(Offer.helper_id == user.id))
        ).all()
    }
    # Active types, plus whatever this person already offers.
    #
    # The list is authoritative — anything missing from it is deleted below — so
    # a screen has to send back rows it is not editing, including any whose
    # category we have since withdrawn. Accepting only active types turns that
    # into a 422 on every save, which is worse than the deletion it prevents:
    # the person cannot change a price at all, and nothing on screen says why.
    #
    # Nobody gains a category this way: to hold one at all it had to be active
    # when the offer was first made. Someone who holds a withdrawn type can add
    # rows under it — another subject, say — and that is accepted on purpose;
    # the alternative is a form that half works for them.
    valid_service_ids = set(
        (await session.scalars(select(ServiceType.id).where(ServiceType.is_active))).all()
    ) | {service_type_id for service_type_id, _, _ in existing}

    # Which checklist lines each kind of help owns, for the filter below. One
    # query for the whole save.
    options_by_service: dict[int, set[int]] = {}
    for service_id, option_id in (
        await session.execute(
            select(ServiceOption.service_type_id, ServiceOption.id).where(
                ServiceOption.is_active.is_(True)
            )
        )
    ).all():
        options_by_service.setdefault(service_id, set()).add(option_id)

    seen_axes: set[tuple[int, int | None, int | None]] = set()
    for offer_spec in spec.offers:
        if offer_spec.service_type_id not in valid_service_ids:
            raise Invalid(f"unknown service type {offer_spec.service_type_id}")
        await require_row(session, Subject, offer_spec.subject_id, "subject_id")
        await require_row(
            session, Institution, offer_spec.institution_id, "institution_id"
        )

        axes = (
            offer_spec.service_type_id,
            offer_spec.subject_id,
            offer_spec.institution_id,
        )
        if axes in seen_axes:
            # The same three axes twice violates uq_offers_axes. Saying which
            # entry is duplicated beats a unique-violation traceback.
            raise Invalid(
                f"duplicate offer for service {axes[0]}, subject {axes[1]}, "
                f"institution {axes[2]}"
            )
        seen_axes.add(axes)

        offer = existing.get(axes)
        is_new = offer is None
        if offer is None:
            offer = Offer(
                helper_id=user.id,
                service_type_id=offer_spec.service_type_id,
                subject_id=offer_spec.subject_id,
                institution_id=offer_spec.institution_id,
            )
            session.add(offer)
        offer.price_amount = offer_spec.price_amount
        offer.price_unit = offer_spec.price_unit
        offer.langs = offer_spec.langs or list(user.spoken_langs)
        # Only the options that belong to this kind of help. A stale client
        # holding yesterday's checklist would otherwise attach insurance's lines
        # to a bank statement, and nothing downstream would notice: the array
        # references nothing, so the labels would simply read as somebody else's.
        offer.option_ids = [
            option_id
            for option_id in offer_spec.option_ids
            if option_id in options_by_service.get(offer_spec.service_type_id, set())
        ]
        offer.note = (offer_spec.note or "").strip() or None
        # Same rule: a caller that said nothing about the format is not saying
        # every offer is now "either way". A row being created still needs one,
        # and the profile's is the only answer that cannot contradict it — the
        # column's own default would put a new service in person for somebody
        # whose page says online only.
        if "work_format" in spec.model_fields_set:
            offer.work_format = spec.work_format
        elif is_new:
            offer.work_format = helper.work_format
        offer.is_active = True

    dropped = [row.id for axes, row in existing.items() if axes not in seen_axes]
    if dropped:
        await session.execute(delete(Offer).where(Offer.id.in_(dropped)))
