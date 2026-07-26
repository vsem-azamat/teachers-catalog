"""What /healthz is allowed to claim about the webhook.

It is the signal the deploy and the shared edge watch, so a false "ok" is
worse than no answer at all: the bot goes deaf and every dial stays green.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


class WebhookBot:
    """Enough of aiogram's Bot to answer "where do my updates go?"."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = 0

    async def get_webhook_info(self):
        self.calls += 1
        return SimpleNamespace(url=self.url)


class SilentBot:
    async def get_webhook_info(self):
        raise RuntimeError("Telegram is having a moment")


@pytest_asyncio.fixture
async def app_with(session: AsyncSession):
    from konnekt.db.session import session_scope, unit_of_work
    from konnekt.main import create_app

    async def scope():
        async with unit_of_work(session):
            yield session

    def build(bot, registration_error: str | None = None) -> FastAPI:
        app = create_app()
        app.dependency_overrides[session_scope] = scope
        app.state.bot = bot
        app.state.webhook_error = registration_error
        app.state.webhook_checked_at = 0.0
        return app

    return build


async def _healthz(app: FastAPI) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/healthz")
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_webhook_telegram_does_not_have_is_not_reported_as_ok(
    app_with,
) -> None:
    """The application remembering a past success is not evidence of one.

    Registration succeeded, and something cleared the webhook afterwards. The
    remembered answer stayed "ok" for as long as the process lived, which is
    exactly the half-failure this endpoint exists to surface.
    """
    body = await _healthz(app_with(WebhookBot("")))
    assert body["webhook"] != "ok"
    assert body["status"] == "ok", "a deaf bot must not take the catalog down"


async def test_a_webhook_pointing_elsewhere_is_not_reported_as_ok(app_with) -> None:
    body = await _healthz(app_with(WebhookBot("https://someone-else.example/tg")))
    assert body["webhook"] != "ok"


async def test_the_webhook_telegram_confirms_is_reported_as_ok(
    app_with, settings
) -> None:
    expected = f"{settings.public_base_url.rstrip('/')}{settings.webhook_path}"
    body = await _healthz(app_with(WebhookBot(expected)))
    assert body["webhook"] == "ok"


async def test_telegram_being_down_does_not_take_the_service_down(app_with) -> None:
    body = await _healthz(app_with(SilentBot()))
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["webhook"] != "ok"


async def test_the_answer_is_cached_so_a_healthcheck_does_not_poll_telegram(
    app_with, settings
) -> None:
    """The container healthcheck hits this every few seconds."""
    expected = f"{settings.public_base_url.rstrip('/')}{settings.webhook_path}"
    bot = WebhookBot(expected)
    app = app_with(bot)

    for _ in range(5):
        await _healthz(app)

    assert bot.calls == 1


async def test_a_service_with_no_bot_says_so(app_with) -> None:
    body = await _healthz(app_with(None))
    assert body["webhook"] == "not configured"


async def test_the_cache_window_is_short_enough_to_notice() -> None:
    """Long enough to spare Telegram, short enough that a deploy sees it."""
    from konnekt.api.v1 import health

    assert 15 <= health.WEBHOOK_CHECK_TTL <= 120


async def test_the_application_logger_actually_writes_somewhere() -> None:
    """The half of the incident that made it undiagnosable.

    Uvicorn configures its own loggers and nothing else, so without this the
    `konnekt` logger falls back to Python's last-resort handler, which emits
    WARNING and above. Every `log.info` went nowhere — including the line that
    says the webhook was registered and where.
    """
    import logging

    from konnekt.main import configure_logging

    configure_logging("INFO")
    logger = logging.getLogger("konnekt")

    assert logger.level == logging.INFO
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    # Asserted against a handler on the root logger rather than through
    # pytest's capture, because propagation is half of what is being claimed:
    # a record that never leaves its own logger reaches nothing a deployment
    # configures either.
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    root = logging.getLogger()
    capture = Capture()
    root.addHandler(capture)
    try:
        logger.info("webhook set to %s", "https://example.test/tg/webhook")
    finally:
        root.removeHandler(capture)

    assert "webhook set to https://example.test/tg/webhook" in seen


async def test_configuring_logging_twice_does_not_double_the_handlers() -> None:
    """`create_app()` runs once per process and once per test."""
    import logging

    from konnekt.main import configure_logging

    configure_logging("INFO")
    before = len(logging.getLogger("konnekt").handlers)
    configure_logging("INFO")
    assert len(logging.getLogger("konnekt").handlers) == before


class HangingBot:
    """Telegram accepting the connection and then saying nothing."""

    async def get_webhook_info(self):
        await asyncio.sleep(60)


async def test_a_telegram_that_hangs_is_given_up_on_with_a_reason(
    app_with, monkeypatch
) -> None:
    """The container healthcheck will not wait, so neither does this.

    And the reason has to survive: `str()` of a bare TimeoutError is empty,
    so a state built from the exception alone reads "unknown: " and explains
    nothing at the moment somebody needs it explained.
    """
    from konnekt.api.v1 import health

    monkeypatch.setattr(health, "WEBHOOK_CHECK_TIMEOUT", 0.05)

    started = time.monotonic()
    body = await _healthz(app_with(HangingBot()))
    elapsed = time.monotonic() - started

    assert body["status"] == "ok"
    assert body["webhook"].startswith("unknown: ")
    assert body["webhook"] != "unknown: "
    assert "TimeoutError" in body["webhook"]
    assert elapsed < 2, f"gave up after {elapsed:.2f}s"


async def test_a_failure_is_retried_sooner_than_a_success_is_rechecked(
    app_with, monkeypatch, settings
) -> None:
    """An outage must not pin the answer for a full minute."""
    from konnekt.api.v1 import health

    assert health.WEBHOOK_FAILURE_TTL < health.WEBHOOK_CHECK_TTL

    expected = f"{settings.public_base_url.rstrip('/')}{settings.webhook_path}"

    class Flaky:
        def __init__(self) -> None:
            self.calls = 0

        async def get_webhook_info(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Telegram is having a moment")
            return SimpleNamespace(url=expected)

    bot = Flaky()
    app = app_with(bot)

    first = await _healthz(app)
    assert first["webhook"].startswith("unknown: ")

    monkeypatch.setattr(health, "WEBHOOK_FAILURE_TTL", 0.0)
    second = await _healthz(app)
    assert second["webhook"] == "ok"
    assert bot.calls == 2


async def test_a_burst_of_probes_asks_telegram_once(settings) -> None:
    """The healthcheck, the edge and a deploy can all arrive together.

    Driven against `webhook_state` rather than through the client: the six
    would otherwise share the test's single AsyncSession, which is not safe to
    use concurrently — a limitation of the fixture, not of the endpoint.
    """
    from konnekt.api.v1.health import webhook_state
    from konnekt.main import create_app

    expected = f"{settings.public_base_url.rstrip('/')}{settings.webhook_path}"

    class Slow:
        def __init__(self) -> None:
            self.calls = 0

        async def get_webhook_info(self):
            self.calls += 1
            await asyncio.sleep(0.05)
            return SimpleNamespace(url=expected)

    bot = Slow()
    app = create_app()
    app.state.bot = bot
    app.state.webhook_error = None
    app.state.webhook_checked_at = 0.0

    answers = await asyncio.gather(*[webhook_state(app) for _ in range(6)])

    assert set(answers) == {"ok"}
    assert bot.calls == 1


async def test_a_registration_failure_is_carried_into_the_missing_message(
    app_with,
) -> None:
    """ "Missing" says the bot is deaf; the registration error says why.

    Without it an operator sees only that there is no webhook, and has to go
    looking for the reason in logs that may already have rotated.
    """
    body = await _healthz(
        app_with(WebhookBot(""), registration_error="Bad Request: bad webhook")
    )
    assert body["webhook"].startswith("missing:")
    assert "Bad Request: bad webhook" in body["webhook"]


async def test_a_slow_probe_does_not_overwrite_a_newer_answer(app_with) -> None:
    """The watch can heal the webhook while a probe is still asking about it.

    The probe then answers with what was true when it started. Writing that
    into the cache would replace a fresh "ok" with a stale "missing" and hold
    it for a full cache window — undoing the heal as far as anyone reading
    /healthz is concerned.
    """
    import time as clock

    from konnekt.api.v1.health import webhook_state

    class Slow:
        async def get_webhook_info(self):
            await asyncio.sleep(0.05)
            return SimpleNamespace(url="")

    app = app_with(Slow())
    app.state.webhook_checked_at = 0.0

    async def heal_midway() -> None:
        await asyncio.sleep(0.02)
        app.state.webhook_observed = "ok"
        app.state.webhook_observed_failed = False
        app.state.webhook_checked_at = clock.monotonic()

    answered, _ = await asyncio.gather(webhook_state(app), heal_midway())

    assert answered.startswith("missing:"), "the probe should say what it saw"
    assert app.state.webhook_observed == "ok", "but it must not cache it over the heal"
