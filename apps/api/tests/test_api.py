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
