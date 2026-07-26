import pytest

from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def test_health_needs_no_auth(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_everything_else_needs_auth(client):
    for path in ("/api/v1/me", "/api/v1/home", "/api/v1/taxonomy/service-types"):
        assert (await client.get(path)).status_code == 401, path


async def test_wrong_scheme_is_rejected(client):
    response = await client.get(
        "/api/v1/me", headers={"Authorization": "Bearer something"}
    )
    assert response.status_code == 401
    assert "tma" in response.json()["detail"]


async def test_first_request_registers_the_user(client):
    response = await client.get(
        "/api/v1/me", headers=auth_header(90101, first_name="Nová")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tg_id"] == 90101
    assert body["name"] == "Nová"
    assert body["is_helper"] is False
    assert body["avatar"]["initials"] == "N"


async def test_language_preference_persists(client):
    headers = auth_header(90102)
    assert (
        await client.patch("/api/v1/me", json={"ui_lang": "cs"}, headers=headers)
    ).status_code == 200
    body = (await client.get("/api/v1/me", headers=headers)).json()
    assert body["ui_lang"] == "cs"


async def test_service_types_are_localised(client):
    headers = auth_header(90103)
    ru = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()
    await client.patch("/api/v1/me", json={"ui_lang": "cs"}, headers=headers)
    cs = (await client.get("/api/v1/taxonomy/service-types", headers=headers)).json()

    assert [s["code"] for s in ru] == [s["code"] for s in cs]
    ru_names = {s["code"]: s["name"] for s in ru}
    cs_names = {s["code"]: s["name"] for s in cs}
    assert ru_names["tutoring"] == "Репетитор по предмету"
    assert cs_names["tutoring"] == "Doučování předmětu"


async def test_home_lists_every_service_type(client):
    body = (await client.get("/api/v1/home", headers=auth_header(90104))).json()
    codes = [s["code"] for s in body["people"]]
    assert "tutoring" in codes
    assert "nostrification" in codes
    # Tones cycle so the client can colour tiles without deciding anything.
    assert all(0 <= s["tone"] < 6 for s in body["people"])


async def test_subject_search_accepts_slang(client):
    response = await client.get(
        "/api/v1/taxonomy/subjects", params={"q": "линал"}, headers=auth_header(90105)
    )
    assert response.status_code == 200
    assert response.json()[0]["slug"] == "linearni-algebra"


async def test_subject_browse_walks_the_tree(client):
    headers = auth_header(90106)
    roots = (await client.get("/api/v1/taxonomy/subjects", headers=headers)).json()
    assert roots, "no root subjects seeded"
    assert all(r["parent_id"] is None for r in roots)
    assert any(r["has_children"] for r in roots)

    parent = next(r for r in roots if r["has_children"])
    children = (
        await client.get(
            "/api/v1/taxonomy/subjects",
            params={"parent_id": parent["id"]},
            headers=headers,
        )
    ).json()
    assert children
    assert all(c["parent_id"] == parent["id"] for c in children)


async def test_parse_returns_chips_and_logs_the_query(client, session):
    from sqlalchemy import func, select

    from konnekt.db.models import SearchQuery

    before = await session.scalar(select(func.count(SearchQuery.id)))
    response = await client.post(
        "/api/v1/search/parse",
        json={"text": "нужен матан на ČVUT, экзамен 14 февраля"},
        headers=auth_header(90107),
    )
    assert response.status_code == 200
    body = response.json()
    kinds = {c["kind"] for c in body["chips"]}
    assert "subject" in kinds
    assert "deadline" in kinds

    after = await session.scalar(select(func.count(SearchQuery.id)))
    assert after == before + 1, "the query was not logged"


async def test_parse_says_so_when_it_understood_nothing(client):
    body = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "zzzz xxxx"},
            headers=auth_header(90108),
        )
    ).json()
    assert body["chips"] == []
    assert body["note"]["code"] == "parse.nothing_recognised"
    assert body["clarify"] is None


async def test_clarify_is_asked_only_when_it_narrows(client):
    """A query that already names the kind of help needs no question."""
    named = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "помощь на экзамене по матану"},
            headers=auth_header(90109),
        )
    ).json()
    assert named["clarify"] is None

    unnamed = (
        await client.post(
            "/api/v1/search/parse",
            json={"text": "матан"},
            headers=auth_header(90110),
        )
    ).json()
    assert unnamed["clarify"]["code"] == "clarify.when"


async def test_search_finds_a_published_helper(client, helper_factory, session):
    await helper_factory(tg_id=91001, first_name="Marek", deals=8)
    await session.flush()

    from sqlalchemy import select

    from konnekt.db.models import Subject

    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id},
            headers=auth_header(90111),
        )
    ).json()
    assert body["total"] >= 1
    names = [r["name"] for r in body["results"]]
    assert "Marek N." in names, names


async def test_helper_page_404s_for_a_draft(client, session):
    from konnekt.db.models import HelperProfile, User
    from konnekt.db.models.enums import PublishStatus

    user = User(tg_id=91002, first_name="Draft")
    session.add(user)
    await session.flush()
    session.add(HelperProfile(user_id=user.id, status=PublishStatus.DRAFT))
    await session.flush()

    response = await client.get(f"/api/v1/helpers/{user.id}", headers=auth_header(90112))
    assert response.status_code == 404


async def test_creating_a_request_reads_the_text(client):
    """The form is one field; everything else comes out of the sentence."""
    response = await client.post(
        "/api/v1/requests",
        json={"text": "нужен матан на ČVUT, экзамен 14 февраля, до 700 kč"},
        headers=auth_header(90201),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["subject"] == "Математический анализ"
    assert body["institution"] == "ČVUT"
    assert body["deadline_on"].endswith("-02-14")
    assert body["status"] == "open"
    assert body["responses_count"] == 0


async def test_requests_are_listed_newest_first(client):
    headers = auth_header(90202)
    await client.post("/api/v1/requests", json={"text": "линал на ČVUT"}, headers=headers)
    await client.post("/api/v1/requests", json={"text": "чешский B2"}, headers=headers)

    body = (await client.get("/api/v1/requests", headers=headers)).json()
    assert len(body) == 2
    assert body[0]["text"] == "чешский B2"


async def test_a_request_without_a_deadline_still_expires(client, session):
    from sqlalchemy import select

    from konnekt.db.models import HelpRequest

    created = (
        await client.post(
            "/api/v1/requests",
            json={"text": "помогите с физикой"},
            headers=auth_header(90203),
        )
    ).json()
    row = await session.scalar(select(HelpRequest).where(HelpRequest.id == created["id"]))
    assert row.expires_at is not None, "a request with no end date would hang forever"


async def test_only_the_author_can_close_a_request(client):
    created = (
        await client.post(
            "/api/v1/requests", json={"text": "матан"}, headers=auth_header(90204)
        )
    ).json()
    other = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(90205)
    )
    assert other.status_code == 404

    mine = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(90204)
    )
    assert mine.status_code == 200
    assert mine.json()["status"] == "closed"


async def test_intro_is_read_into_a_draft_profile(client):
    """The onboarding form is one field; the rest is extracted and shown back."""
    body = (
        await client.post(
            "/api/v1/helper/intro",
            json={
                "text": (
                    "Учусь на FEL, третий курс. Могу подтянуть матан и линейку, "
                    "сам сдавал на A. Беру 500 в час, онлайн или в Дейвице."
                )
            },
            headers=auth_header(90301),
        )
    ).json()

    labels = [c["label"] for c in body["chips"] if c["kind"] == "subject"]
    assert "Математический анализ" in labels
    assert body["price"]["amount"] == 500
    assert body["price"]["unit"] == "hour"
    assert body["institution_id"] is not None
    # Nothing in the text says when they are free, and that is worth asking for.
    assert "availability" in body["missing"]


async def test_publishing_makes_the_profile_findable(client, session):
    from sqlalchemy import select

    from konnekt.db.models import ServiceType, Subject

    headers = auth_header(90302, first_name="Nový")
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(
        select(Subject).where(Subject.slug == "linearni-algebra")
    )

    before = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()["total"]

    saved = await client.put(
        "/api/v1/helper",
        json={
            "headline": "ČVUT FEL · 3. ročník",
            "about": "Podtahuju linearni algebru.",
            "work_format": "both",
            "publish": True,
            "offers": [
                {
                    "service_type_id": service.id,
                    "subject_id": subject.id,
                    "price_amount": 500,
                    "price_unit": "hour",
                    "langs": ["ru", "cs"],
                }
            ],
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["is_helper"] is True
    assert saved.json()["helper_status"] == "published"

    after = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()
    assert after["total"] == before + 1


async def test_an_unpublished_profile_stays_out_of_search(client, session):
    from sqlalchemy import select

    from konnekt.db.models import ServiceType, Subject

    headers = auth_header(90303)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(select(Subject).where(Subject.slug == "genetika"))

    await client.put(
        "/api/v1/helper",
        json={
            "publish": False,
            "offers": [{"service_type_id": service.id, "subject_id": subject.id}],
        },
        headers=headers,
    )
    found = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()
    assert found["total"] == 0


async def test_offers_are_replaced_not_appended(client, session):
    """The client sends the whole set; a diff would leave deleted rows behind."""
    from sqlalchemy import select

    from konnekt.db.models import ServiceType, Subject

    headers = auth_header(90304)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    first = await session.scalar(select(Subject).where(Subject.slug == "fyzika-1"))
    second = await session.scalar(select(Subject).where(Subject.slug == "fyzika-2"))

    async def total(subject_id: int) -> int:
        response = await client.get(
            "/api/v1/search", params={"subject_id": subject_id}, headers=headers
        )
        return response.json()["total"]

    # Deltas, not absolutes: the development database carries demo helpers and
    # one of them already teaches physics.
    before_first, before_second = await total(first.id), await total(second.id)

    for subject in (first, second):
        await client.put(
            "/api/v1/helper",
            json={
                "publish": True,
                "offers": [{"service_type_id": service.id, "subject_id": subject.id}],
            },
            headers=headers,
        )

    assert await total(first.id) == before_first, "the replaced offer survived"
    assert await total(second.id) == before_second + 1


async def test_an_unknown_service_type_is_refused(client):
    response = await client.put(
        "/api/v1/helper",
        json={"offers": [{"service_type_id": 999999}]},
        headers=auth_header(90305),
    )
    assert response.status_code == 422


async def test_hiding_a_published_profile_takes_it_out_of_the_catalog(client, session):
    """ "Hide me" has to actually hide; it used to be a no-op once published."""
    from sqlalchemy import select

    from konnekt.db.models import ServiceType, Subject

    headers = auth_header(90401)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(select(Subject).where(Subject.slug == "histologie"))
    offers = [{"service_type_id": service.id, "subject_id": subject.id}]

    await client.put(
        "/api/v1/helper", json={"publish": True, "offers": offers}, headers=headers
    )
    published = (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()["total"]
    assert published == 1

    hidden = await client.put(
        "/api/v1/helper", json={"publish": False, "offers": offers}, headers=headers
    )
    assert hidden.json()["helper_status"] == "hidden"
    assert (
        await client.get(
            "/api/v1/search", params={"subject_id": subject.id}, headers=headers
        )
    ).json()["total"] == 0


async def test_a_banned_profile_cannot_publish_itself(client, session):
    from konnekt.db.models import HelperProfile
    from konnekt.db.models.enums import PublishStatus

    headers = auth_header(90402)
    await client.get("/api/v1/me", headers=headers)  # registers the account
    await client.put("/api/v1/helper", json={"publish": False}, headers=headers)

    from sqlalchemy import select

    from konnekt.db.models import User

    user = await session.scalar(select(User).where(User.tg_id == 90402))
    helper = await session.get(HelperProfile, user.id)
    helper.status = PublishStatus.BANNED
    await session.commit()

    refused = await client.put("/api/v1/helper", json={"publish": True}, headers=headers)
    assert refused.status_code == 403


async def test_the_same_axes_twice_is_a_422_not_a_traceback(client, session):
    from sqlalchemy import select

    from konnekt.db.models import ServiceType, Subject

    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "tutoring")
    )
    subject = await session.scalar(select(Subject).where(Subject.slug == "genetika"))
    duplicate = {"service_type_id": service.id, "subject_id": subject.id}

    response = await client.put(
        "/api/v1/helper",
        json={"offers": [duplicate, duplicate]},
        headers=auth_header(90403),
    )
    assert response.status_code == 422
    assert "duplicate" in response.json()["detail"]


async def test_unknown_foreign_keys_are_named_not_crashed(client):
    headers = auth_header(90404)
    bad_institution = await client.patch(
        "/api/v1/me", json={"institution_id": 999999}, headers=headers
    )
    assert bad_institution.status_code == 422
    assert "institution_id" in bad_institution.json()["detail"]

    bad_subject = await client.post(
        "/api/v1/requests",
        json={"text": "матан", "subject_id": 999999},
        headers=headers,
    )
    assert bad_subject.status_code == 422


async def test_one_person_appears_once_however_many_offers_match(
    client, session, helper_factory
):
    """Two matching offers is a reason to rank higher, not to show twice."""
    from sqlalchemy import select

    from konnekt.db.models import Offer, ServiceType, Subject

    user = await helper_factory(tg_id=91101, subject_slug="anatomie")
    subject = await session.scalar(select(Subject).where(Subject.slug == "anatomie"))
    second = await session.scalar(
        select(ServiceType).where(ServiceType.code == "exam_prep")
    )
    session.add(
        Offer(
            helper_id=user.id,
            service_type_id=second.id,
            subject_id=subject.id,
            price_amount=800,
        )
    )
    await session.flush()

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id},
            headers=auth_header(90405),
        )
    ).json()
    assert body["total"] == 1
    assert len(body["results"]) == 1


async def test_clicking_an_unknown_placement_is_a_404(client):
    response = await client.post(
        "/api/v1/placements/999999/click", headers=auth_header(90406)
    )
    assert response.status_code == 404


async def test_an_unknown_placement_slot_is_rejected(client):
    response = await client.get(
        "/api/v1/placements", params={"slot": "nowhere"}, headers=auth_header(90407)
    )
    assert response.status_code == 422


async def test_partner_blocks_are_matched_by_condition(client):
    """Sworn translation belongs on the nostrification screen, not everywhere."""
    on_topic = (
        await client.get(
            "/api/v1/placements",
            params={"slot": "screen_nostrification", "service_type": "nostrification"},
            headers=auth_header(90408),
        )
    ).json()
    assert any("překlad" in p["title"] or "перевод" in p["title"] for p in on_topic)

    off_topic = (
        await client.get(
            "/api/v1/placements",
            params={"slot": "screen_nostrification"},
            headers=auth_header(90409),
        )
    ).json()
    assert off_topic == []


async def test_paging_bounds_are_enforced(client):
    headers = auth_header(90410)
    assert (
        await client.get("/api/v1/search", params={"offset": -1}, headers=headers)
    ).status_code == 422
    assert (
        await client.get("/api/v1/search", params={"limit": 0}, headers=headers)
    ).status_code == 422


async def test_a_failing_handler_still_answers_the_webhook(monkeypatch):
    """Telegram redelivers anything that is not a 200.

    A handler that throws on one message would otherwise have the same update
    pushed back at the webhook until Telegram gives up on the bot. The update
    was received either way; the failure belongs in our log.
    """
    from httpx import ASGITransport, AsyncClient

    from konnekt.core.config import get_settings
    from konnekt.main import create_app

    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "probe-secret", raising=False)

    class ExplodingDispatcher:
        async def feed_update(self, *_args, **_kwargs):
            raise RuntimeError("handler blew up")

    app = create_app()
    app.state.bot = object()
    app.state.dispatcher = ExplodingDispatcher()

    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1_700_000_000,
            "chat": {"id": 1, "type": "private"},
            "text": "/start",
        },
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(
            settings.webhook_path,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "probe-secret"},
        )
    assert response.status_code == 200


async def test_the_webhook_refuses_to_serve_without_a_secret(monkeypatch):
    """Fail closed: an open webhook lets anyone speak as the bot."""
    from httpx import ASGITransport, AsyncClient

    from konnekt.core.config import get_settings
    from konnekt.main import create_app

    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "", raising=False)

    app = create_app()
    app.state.bot = object()
    app.state.dispatcher = object()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(settings.webhook_path, json={"update_id": 1})
    assert response.status_code == 503


async def test_a_matching_institution_ranks_above_one_without(
    client, session, helper_factory
):
    """`institution_id = :x` is NULL when the offer has none.

    Postgres sorts NULLs first under DESC, so the offers that did not match the
    requested school were coming out above the ones that did.
    """
    from sqlalchemy import select

    from konnekt.db.models import Institution, Subject

    subject = await session.scalar(select(Subject).where(Subject.slug == "biochemie"))
    cvut = await session.scalar(select(Institution).where(Institution.code == "cvut"))

    await helper_factory(
        tg_id=91201,
        first_name="Unattached",
        last_name=None,
        subject_slug="biochemie",
        institution_id=None,
        price=100,
    )
    await helper_factory(
        tg_id=91202,
        first_name="Attached",
        last_name=None,
        subject_slug="biochemie",
        institution_id=cvut.id,
        price=900,
    )
    await session.flush()

    body = (
        await client.get(
            "/api/v1/search",
            params={"subject_id": subject.id, "institution_id": cvut.id},
            headers=auth_header(90501),
        )
    ).json()

    names = [r["name"] for r in body["results"]]
    assert names[0] == "Attached", names
    assert body["results"][0]["reason"]["code"].startswith("reason.same")


async def test_search_reports_what_it_is_filtering_on(client, session):
    from sqlalchemy import select

    from konnekt.db.models import Institution, Subject

    subject = await session.scalar(
        select(Subject).where(Subject.slug == "matematicka-analyza")
    )
    cvut = await session.scalar(select(Institution).where(Institution.code == "cvut"))

    body = (
        await client.get(
            "/api/v1/search",
            params={
                "subject_id": subject.id,
                "institution_id": cvut.id,
                "max_price": 700,
            },
            headers=auth_header(90502),
        )
    ).json()

    kinds = {chip["kind"]: chip["label"] for chip in body["chips"]}
    assert kinds["subject"] == "Математический анализ"
    assert kinds["institution"] == "ČVUT"
    assert kinds["budget"] == "700"
