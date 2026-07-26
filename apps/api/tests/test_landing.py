"""The one endpoint a browser is allowed to hit.

The landing page's button points at `/api/v1/open`, so the bot's handle lives
in the token the server already has rather than in the frontend bundle and the
build. That makes this the only unauthenticated route in the API, which is
worth pinning down.
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


class StubBot:
    """Enough of aiogram's Bot to answer "what is your username?"."""

    def __init__(self, username: str) -> None:
        self.username = username
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        return SimpleNamespace(username=self.username)


class BrokenBot:
    async def get_me(self):
        raise RuntimeError("Telegram is having a moment")


@pytest_asyncio.fixture
async def app_with(session: AsyncSession):
    """An app with a bot of the caller's choosing on its state."""
    from konnekt.db.session import session_scope
    from konnekt.main import create_app

    async def build(bot) -> FastAPI:
        app = create_app()
        app.dependency_overrides[session_scope] = lambda: session
        app.state.bot = bot
        return app

    return build


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_open_redirects_to_the_bot(app_with) -> None:
    bot = StubBot("student_cz_bot")
    app = await app_with(bot)

    async with await _client(app) as http:
        response = await http.get("/api/v1/open")

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/student_cz_bot"


async def test_open_needs_no_init_data(app_with) -> None:
    """The whole point: this is reached by someone not in Telegram yet."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open")

    assert response.status_code == 302
    assert "Authorization" not in response.request.headers


async def test_the_handle_is_asked_for_once(app_with) -> None:
    """Every landing visit would otherwise be a round trip to Telegram."""
    bot = StubBot("student_cz_bot")
    app = await app_with(bot)

    async with await _client(app) as http:
        await http.get("/api/v1/open")
        await http.get("/api/v1/open")

    assert bot.calls == 1


async def test_without_a_bot_it_says_so(client: AsyncClient) -> None:
    """The shared client has no bot on its state — the API-only configuration."""
    response = await client.get("/api/v1/open")

    assert response.status_code == 503


async def test_a_failing_telegram_is_not_a_crash(app_with) -> None:
    app = await app_with(BrokenBot())

    async with await _client(app) as http:
        response = await http.get("/api/v1/open")

    assert response.status_code == 503
