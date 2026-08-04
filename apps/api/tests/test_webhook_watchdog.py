"""The webhook is Telegram's state, not ours, and it can be taken away.

Anything holding the same bot token can clear it — a stray `deleteWebhook`, or
a `polling` bot, which deletes it on every start. Registering once at boot
therefore is not enough: the application has to keep checking that Telegram
still points here.
"""

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.asyncio


class Telegram:
    """Enough of aiogram's Bot to hold — and lose — a webhook."""

    def __init__(self, *, clear_after: int | None = None) -> None:
        self.url = ""
        self.sets = 0
        self.reads = 0
        self.clear_after = clear_after
        self.dropped: list[bool] = []

    async def set_webhook(self, url: str, **kwargs: object) -> None:
        self.sets += 1
        self.url = url
        self.dropped.append(bool(kwargs.get("drop_pending_updates")))

    async def set_chat_menu_button(self, **_: object) -> None:
        """Called right after registration, to point the menu at the app."""

    async def set_my_commands(self, *_: object, **__: object) -> None:
        """And the command list beside it — see `bot.configure`."""

    async def get_webhook_info(self):
        self.reads += 1
        if self.clear_after is not None and self.reads >= self.clear_after:
            # Somebody else called deleteWebhook between our reads.
            self.url = ""
        return SimpleNamespace(url=self.url)


def _app() -> FastAPI:
    """A real app, because that is what the watch is annotated to take."""
    app = FastAPI()
    app.state.webhook_error = None
    return app


def _dispatcher() -> SimpleNamespace:
    return SimpleNamespace(resolve_used_update_types=lambda: ["message"])


async def _run_briefly(coro, seconds: float = 0.4) -> None:
    task = asyncio.create_task(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def test_a_webhook_cleared_by_someone_else_is_set_again(settings) -> None:
    from students_cz.main import keep_webhook_registered

    bot = Telegram(clear_after=1)
    app = _app()

    await _run_briefly(
        keep_webhook_registered(app, bot, _dispatcher(), settings, recheck_seconds=0.05)
    )

    assert bot.sets > 1, "the webhook was set once and never restored"
    assert bot.url == settings.webhook_url


async def test_a_webhook_that_stays_put_is_not_set_again(settings) -> None:
    """Re-registering for no reason would drop pending updates every minute."""
    from students_cz.main import keep_webhook_registered

    bot = Telegram()
    app = _app()

    await _run_briefly(
        keep_webhook_registered(app, bot, _dispatcher(), settings, recheck_seconds=0.05)
    )

    assert bot.sets == 1
    assert bot.reads > 1, "it should have kept checking"


async def test_telegram_failing_a_check_does_not_end_the_watch(settings) -> None:
    from students_cz.main import keep_webhook_registered

    class Flaky(Telegram):
        async def get_webhook_info(self):
            self.reads += 1
            if self.reads == 1:
                raise RuntimeError("Telegram is having a moment")
            return SimpleNamespace(url=self.url)

    bot = Flaky()
    app = _app()

    await _run_briefly(
        keep_webhook_registered(app, bot, _dispatcher(), settings, recheck_seconds=0.05)
    )

    assert bot.reads > 2, "one failed check ended the watch"


async def test_healing_keeps_the_updates_that_queued_while_it_was_deaf(
    settings,
) -> None:
    """The messages that arrived during the outage are the point of the watch.

    `set_webhook(drop_pending_updates=True)` throws away everything Telegram
    queued. That is right at boot — those predate the process — and wrong on a
    heal, where the queue is exactly what the outage cost.
    """
    from students_cz.main import keep_webhook_registered

    bot = Telegram(clear_after=1)
    await _run_briefly(
        keep_webhook_registered(
            _app(), bot, _dispatcher(), settings, recheck_seconds=0.05
        )
    )

    assert bot.dropped[0] is True, "the first registration should start clean"
    assert all(dropped is False for dropped in bot.dropped[1:]), (
        f"a heal discarded queued updates: {bot.dropped}"
    )


async def test_a_check_that_hangs_does_not_stop_the_watch(settings) -> None:
    """Without a timeout the watch waits as long as aiogram's session will."""
    from students_cz.main import keep_webhook_registered

    class Hanging(Telegram):
        async def get_webhook_info(self):
            self.reads += 1
            await asyncio.sleep(30)

    bot = Hanging()
    await _run_briefly(
        keep_webhook_registered(
            _app(),
            bot,
            _dispatcher(),
            settings,
            recheck_seconds=0.02,
            recheck_timeout=0.02,
        ),
        seconds=0.3,
    )

    assert bot.reads > 2, f"the watch stopped after {bot.reads} check(s)"


async def test_the_check_is_given_up_on_before_the_next_one_is_due(settings) -> None:
    """Otherwise checks pile up on each other."""
    from students_cz import main

    assert main.WEBHOOK_RECHECK_TIMEOUT < main.WEBHOOK_RECHECK_SECONDS


async def test_what_the_watch_saw_is_handed_to_healthz(settings) -> None:
    """One asker, not two: /healthz reuses this rather than repeating the call."""
    from students_cz.main import keep_webhook_registered

    app = _app()
    bot = Telegram()
    await _run_briefly(
        keep_webhook_registered(app, bot, _dispatcher(), settings, recheck_seconds=0.05)
    )

    assert app.state.webhook_observed == "ok"
    assert app.state.webhook_checked_at > 0


async def test_healthz_is_told_the_moment_the_webhook_is_back(settings) -> None:
    """Otherwise the endpoint serves its cached pre-heal reading for a minute.

    Which would mean reporting a deaf bot for as long after the fix as the
    outage itself lasted — during exactly the incident this watch exists for.
    """
    from students_cz.main import keep_webhook_registered

    app = _app()
    bot = Telegram(clear_after=1)
    await _run_briefly(
        keep_webhook_registered(app, bot, _dispatcher(), settings, recheck_seconds=0.05)
    )

    assert bot.sets > 1, "no heal happened, so this proves nothing"
    assert app.state.webhook_observed == "ok"


async def test_the_watch_reports_a_missing_webhook_in_the_endpoint_s_words(
    settings,
) -> None:
    """One vocabulary, so /healthz reads the same either way."""
    from students_cz.api.v1.health import name_webhook_state
    from students_cz.main import _publish

    app = _app()
    app.state.webhook_error = "Bad Request: bad webhook"
    _publish(app, "", expected=settings.webhook_url)

    assert app.state.webhook_observed == name_webhook_state(
        "", expected=settings.webhook_url, registration_error="Bad Request: bad webhook"
    )
    assert "Bad Request: bad webhook" in app.state.webhook_observed
