"""What the operator reads in the console, and who may read it.

The console lives in supervisor-telegram's app; the catalog's part of it is
two read-only lists behind `ADMIN_TG_IDS`. See docs/architecture.md, «The
operator reads, and only reads».
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.core.config import Settings, get_settings
from students_cz.db.models import HelperProfile, User
from students_cz.db.models.enums import (
    PlacementEventKind,
    PlacementSlot,
    RequestStatus,
    UiLang,
)
from students_cz.db.models.ops import SearchQuery
from students_cz.db.models.partners import (
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    Placement,
    PlacementEvent,
)
from students_cz.db.models.requests import HelpRequest, RequestResponse

from .conftest import app_for, auth_header

pytestmark = pytest.mark.asyncio

OPERATOR = 97001
STRANGER = 97002


def _client(
    session: AsyncSession, admins: tuple[int, ...] | str = (OPERATOR,)
) -> AsyncClient:
    app = app_for(session)
    ids = admins if isinstance(admins, str) else list(admins)
    configured = Settings(_env_file=None, admin_tg_ids=ids)
    app.dependency_overrides[get_settings] = lambda: configured
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── who ─────────────────────────────────────────────────────────────────


async def test_me_says_who_is_an_operator(session: AsyncSession) -> None:
    async with _client(session) as http:
        operator = await http.get("/api/v1/me", headers=auth_header(OPERATOR))
        stranger = await http.get("/api/v1/me", headers=auth_header(STRANGER))

    assert operator.json()["is_admin"] is True
    assert stranger.json()["is_admin"] is False


@pytest.mark.parametrize("path", ["/api/v1/admin/catalog", "/api/v1/admin/partners"])
async def test_everybody_else_is_refused(session: AsyncSession, path: str) -> None:
    async with _client(session) as http:
        response = await http.get(path, headers=auth_header(STRANGER))

    assert response.status_code == 403


async def test_nobody_is_an_operator_unless_named(session: AsyncSession) -> None:
    async with _client(session, admins="") as http:
        response = await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))

    assert response.status_code == 403


def test_the_list_is_read_as_the_deploy_writes_it() -> None:
    """Comma-separated, like supervisor's ADMIN_SUPER_ADMINS; a typo refuses to start."""
    assert Settings(_env_file=None, admin_tg_ids="1, 22").admin_tg_ids == [1, 22]
    assert Settings(_env_file=None, admin_tg_ids="").admin_tg_ids == []
    with pytest.raises(ValidationError):
        Settings(_env_file=None, admin_tg_ids="1,@me")


# ── the catalog ─────────────────────────────────────────────────────────


async def _person(session: AsyncSession, tg_id: int, name: str) -> User:
    user = User(tg_id=tg_id, first_name=name, ui_lang=UiLang.RU, spoken_langs=["ru"])
    session.add(user)
    await session.flush()
    return user


async def test_new_profiles_are_the_last_weeks_newest_first(
    session: AsyncSession, helper_factory
) -> None:
    now = datetime.now(UTC)
    fresh = await helper_factory(tg_id=97101, first_name="Marina", last_name=None)
    older = await helper_factory(tg_id=97102, first_name="Olga", last_name=None)
    stale = await helper_factory(tg_id=97103, first_name="Petr", last_name=None)
    for user, age in ((fresh, 1), (older, 3), (stale, 10)):
        profile = await session.get(HelperProfile, user.id)
        assert profile is not None
        profile.published_at = now - timedelta(days=age)
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    names = [row["name"] for row in body["profiles"]]
    assert names[:2] == ["Marina", "Olga"]
    assert "Petr" not in names
    assert body["profiles"][0]["services"], "what they offer, by service name"
    assert body["counts"]["profiles_week"] >= 2
    # A display name and nothing to reach them by.
    assert set(body["profiles"][0]) == {"user_id", "name", "services", "published_at"}


async def test_unanswered_requests_are_open_ones_nobody_answered_oldest_first(
    session: AsyncSession, helper_factory
) -> None:
    now = datetime.now(UTC)
    author = await _person(session, 97201, "Anna")
    helper = await helper_factory(tg_id=97202)

    def ask(text: str, status: RequestStatus = RequestStatus.OPEN) -> HelpRequest:
        return HelpRequest(author_id=author.id, raw_text=text, status=status)

    waiting_long = ask("курсовая по микроэкономике")
    waiting = ask("přijímačky на медицину")
    answered = ask("матан к экзамену")
    closed = ask("уже не надо", RequestStatus.CLOSED)
    draft = ask("ещё пишу", RequestStatus.DRAFT)
    for request in (waiting_long, waiting, answered, closed, draft):
        session.add(request)
    await session.flush()
    waiting_long.created_at = now - timedelta(days=5)
    waiting.created_at = now - timedelta(days=1)
    session.add(
        RequestResponse(request_id=answered.id, helper_id=helper.id, message="могу")
    )
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    texts = [row["text"] for row in body["unanswered"]]
    assert texts.index("курсовая по микроэкономике") < texts.index(
        "přijímačky на медицину"
    )
    assert "матан к экзамену" not in texts
    assert "уже не надо" not in texts
    assert "ещё пишу" not in texts, "a draft is not a request yet"
    assert body["counts"]["unanswered"] == len(texts)


async def test_failed_searches_are_grouped_by_text_most_frequent_first(
    session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    rows = [
        ("AutoCAD", 0, 2),
        ("autocad ", 0, 3),
        ("микроэкономика", 0, 1),
        ("микроэкономика", 0, 2),
        ("микроэкономика", 0, 4),
        ("матан", 5, 1),
        ("латынь", 0, 40),
    ]
    for text, found, age in rows:
        query = SearchQuery(raw_text=text, results_count=found)
        session.add(query)
        await session.flush()
        query.created_at = now - timedelta(days=age)
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        ).json()

    failed = {row["text"].lower(): row["times"] for row in body["failed_searches"]}
    assert list(failed)[:2] == ["микроэкономика", "autocad"]
    assert failed["микроэкономика"] == 3
    assert failed["autocad"] == 2, "case and trailing spaces are the same search"
    assert "матан" not in failed, "it found something"
    assert "латынь" not in failed, "older than 30 days"


# ── the partners ────────────────────────────────────────────────────────


async def test_placements_carry_their_last_months_impressions_and_clicks(
    session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    partner = Partner(code="admin-test-insurer", name="Insurer")
    session.add(partner)
    await session.flush()
    offer = PartnerOffer(partner_id=partner.id, url="https://example.test/offer")
    session.add(offer)
    await session.flush()
    session.add(PartnerOfferI18n(offer_id=offer.id, lang=UiLang.RU, title="Страховка"))
    live = Placement(offer_id=offer.id, slot=PlacementSlot.SCREEN_LIFE)
    off = Placement(offer_id=offer.id, slot=PlacementSlot.PROFILE_FOOTER, is_active=False)
    session.add_all([live, off])
    await session.flush()
    events = [
        (PlacementEventKind.IMPRESSION, 1),
        (PlacementEventKind.IMPRESSION, 2),
        (PlacementEventKind.IMPRESSION, 45),
        (PlacementEventKind.CLICK, 3),
    ]
    for kind, age in events:
        event = PlacementEvent(placement_id=live.id, kind=kind)
        session.add(event)
        await session.flush()
        event.created_at = now - timedelta(days=age)
    await session.flush()

    async with _client(session) as http:
        body = (
            await http.get("/api/v1/admin/partners", headers=auth_header(OPERATOR))
        ).json()

    rows = {row["placement_id"]: row for row in body}
    assert rows[live.id]["impressions"] == 2
    assert rows[live.id]["clicks"] == 1
    assert rows[live.id]["partner"] == "Insurer"
    assert rows[live.id]["title"] == "Страховка"
    assert rows[live.id]["slot"] == "screen_life"
    assert rows[live.id]["is_active"] is True
    assert rows[off.id]["is_active"] is False
    assert rows[off.id]["impressions"] == 0
