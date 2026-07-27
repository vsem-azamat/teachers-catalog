"""One process: the API, the bot webhook, and eventually the mini app's build.

Keeping them together is not laziness — it is what makes the origin rule work.
Since 20 July 2026 Telegram only allows Mini App API calls from the app's own
origin, so the page and the API it talks to have to be the same host anyway.
"""

import asyncio
import logging
import secrets
import time as clock
from contextlib import asynccontextmanager, suppress

from aiogram.types import Update
from fastapi import FastAPI, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from students_cz.api.v1 import router as api_router
from students_cz.api.v1.health import health_router, name_webhook_state
from students_cz.bot import build_bot, build_dispatcher, configure
from students_cz.core.config import get_settings
from students_cz.db.session import dispose_engine
from students_cz.services import errors

log = logging.getLogger("students_cz")


def configure_logging(level: str) -> None:
    """Give this application's logger somewhere to write.

    Uvicorn configures its own loggers and nothing else, so without this the
    `students_cz` logger has no handler and falls back to Python's last-resort
    one — which only emits WARNING and above. Every `log.info` in the process
    went nowhere, including the line that says the webhook was registered and
    where, which is precisely the line wanted when the bot goes quiet.

    Records still propagate. Uvicorn does not configure the root logger, so
    there is nothing to duplicate against, and cutting propagation would also
    cut off whatever a deployment attaches there with `--log-config`.
    """
    log.setLevel(level)
    if any(isinstance(handler, logging.StreamHandler) for handler in log.handlers):
        # `create_app()` runs once per process, and once per test.
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    log.addHandler(handler)


# Backoff for webhook registration: quick at first, because the usual cause is
# a DNS record that has just been created, then patient, because the other
# cause is Telegram itself and there is nothing to gain by hammering it.
WEBHOOK_RETRY_DELAYS = (5, 15, 60, 180, 300)


# How often Telegram is asked whether it still points here. A webhook that has
# been cleared costs at most this much silence.
WEBHOOK_RECHECK_SECONDS = 60.0

# The recheck must not outlive its interval, or a hanging call would stop the
# watch for as long as aiogram's default session is willing to wait.
WEBHOOK_RECHECK_TIMEOUT = 10.0


async def keep_webhook_registered(
    app: FastAPI,
    bot,
    dispatcher,
    settings,
    recheck_seconds: float = WEBHOOK_RECHECK_SECONDS,
    recheck_timeout: float = WEBHOOK_RECHECK_TIMEOUT,
) -> None:
    """Point Telegram at us, and keep it pointed.

    Registration is not a thing that happens once. The webhook is state held
    by Telegram, and anything holding the same bot token can take it away —
    `deleteWebhook` from a stray process, or a `polling` bot, which deletes it
    on every start. Without this the bot goes deaf until somebody restarts the
    process, and nothing says why.

    Re-registering is deliberately conditional: `set_webhook` on a timer would
    be a call to Telegram every minute for nothing. When it does have to
    happen, it keeps whatever queued while the bot was deaf — those are the
    messages the outage was about.
    """
    # Dropping what queued before the process existed is right at boot, and
    # wrong on a heal — see below.
    await _set_webhook(app, bot, dispatcher, settings, drop_pending=True)

    while True:
        await asyncio.sleep(recheck_seconds)
        try:
            info = await asyncio.wait_for(bot.get_webhook_info(), timeout=recheck_timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A check we could not make says nothing about the webhook, and is
            # not a reason to stop making them.
            log.warning("could not check the webhook: %s", str(exc) or type(exc).__name__)
            continue

        observed = str(getattr(info, "url", "") or "")
        _publish(app, observed, expected=settings.webhook_url)
        if observed == settings.webhook_url:
            continue

        if observed:
            log.error(
                "the webhook points at %s, not at %s — something else is holding "
                "this bot token and setting its own. Setting ours again; if this "
                "repeats, the two are taking turns and one of them has to stop",
                observed,
                settings.webhook_url,
            )
        else:
            log.error(
                "webhook was cleared by someone else — setting it again. Something "
                "else is holding this bot token; a polling bot deletes the webhook "
                "on every start"
            )

        # drop_pending=False: whatever queued while the bot was deaf is exactly
        # what this watch exists to save. Dropping it here would throw away the
        # messages the outage was about.
        await _set_webhook(app, bot, dispatcher, settings, drop_pending=False)
        # Say so immediately. Otherwise /healthz serves the pre-heal reading
        # from its cache and reports a deaf bot for up to a minute after it
        # can hear again.
        _publish(app, settings.webhook_url, expected=settings.webhook_url)


def _publish(app: FastAPI, observed: str, *, expected: str) -> None:
    """Hand the observation to /healthz, so Telegram is asked once, not twice.

    The endpoint keeps its own ability to ask — it has to answer when no watch
    is running — but while one is, this is the fresher answer and the endpoint
    reuses it rather than repeating the call seconds later. The wording is the
    endpoint's, not a second copy of it.
    """
    app.state.webhook_observed = name_webhook_state(
        observed,
        expected=expected,
        registration_error=getattr(app.state, "webhook_error", None),
    )
    app.state.webhook_observed_failed = False
    app.state.webhook_checked_at = clock.monotonic()


async def _set_webhook(
    app: FastAPI, bot, dispatcher, settings, *, drop_pending: bool
) -> None:
    """Ask Telegram to send updates here, retrying until it agrees."""
    url = settings.webhook_url
    attempt = 0
    while True:
        try:
            await bot.set_webhook(
                url=url,
                secret_token=settings.webhook_secret,
                # Only the update types something actually handles, so Telegram
                # stops sending the rest.
                allowed_updates=dispatcher.resolve_used_update_types(),
                drop_pending_updates=drop_pending,
            )
            await configure(bot, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            attempt += 1
            delay = WEBHOOK_RETRY_DELAYS[min(attempt - 1, len(WEBHOOK_RETRY_DELAYS) - 1)]
            app.state.webhook_error = str(exc) or type(exc).__name__
            log.error("webhook not registered (attempt %s): %s", attempt, exc)
            await asyncio.sleep(delay)
        else:
            app.state.webhook_error = None
            log.info("webhook set to %s", url)
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.bot = None
    app.state.dispatcher = None
    app.state.webhook_task = None
    # Why registration failed, if it did. Whether there *is* a webhook is
    # Telegram's to answer, and /healthz asks it — a status remembered here
    # would be the same fiction that let a deaf bot pass every health check.
    app.state.webhook_error = None

    if settings.bot_token:
        bot = build_bot(settings)
        dispatcher = build_dispatcher(settings)
        # Injected into every handler, so handlers never reach for a global.
        dispatcher["settings"] = settings
        app.state.bot, app.state.dispatcher = bot, dispatcher

        await dispatcher.emit_startup(bot=bot, dispatcher=dispatcher)
        if settings.public_base_url:
            if not settings.webhook_secret:
                raise RuntimeError(
                    "PUBLIC_BASE_URL is set but WEBHOOK_SECRET is not — refusing "
                    "to register a webhook nobody can authenticate"
                )
            # In the background, and retried. Telegram refuses a webhook whose
            # host does not resolve yet, and it has hour-long bad gateway
            # windows of its own; neither is a reason for the catalog to be
            # down. The state is reported by /healthz so a webhook that never
            # registers is visible rather than merely quiet.
            app.state.webhook_task = asyncio.create_task(
                keep_webhook_registered(app, bot, dispatcher, settings)
            )
        else:
            log.warning("PUBLIC_BASE_URL is unset — bot is loaded but not reachable")
    else:
        log.warning("BOT_TOKEN is unset — running API-only")

    yield

    task = app.state.webhook_task
    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    # Read once into locals: the two are set together above, and testing them
    # together is what says so to anything reading this later.
    bot, dispatcher = app.state.bot, app.state.dispatcher
    if bot is not None and dispatcher is not None:
        await dispatcher.emit_shutdown(bot=bot, dispatcher=dispatcher)
        # Without this the aiohttp session behind the bot leaks on reload.
        await bot.session.close()
    await dispose_engine()


SERVICE_ERROR_STATUS: dict[type[errors.ServiceError], int] = {
    errors.NotFound: status.HTTP_404_NOT_FOUND,
    errors.Forbidden: status.HTTP_403_FORBIDDEN,
    errors.Conflict: status.HTTP_409_CONFLICT,
    errors.Invalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.BadRequest: status.HTTP_400_BAD_REQUEST,
}


def status_for(exc: BaseException) -> int:
    """The status a service error answers with, following the class hierarchy.

    Walked rather than looked up: an exact-type lookup turns a subclass of
    `Invalid` — or the base class raised by mistake — into a KeyError inside
    the error handler, which is a 500 with no body at all. An unmapped one is
    still a programming error, so it is logged rather than quietly given a
    plausible status.
    """
    for klass in type(exc).__mro__:
        mapped = SERVICE_ERROR_STATUS.get(klass)
        if mapped is not None:
            return mapped
    log.error("no status mapped for %s", type(exc).__name__)
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Konnekt",
        description="Student help catalog for the Czech Republic",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # The one place a service's vocabulary becomes a status code. Services
    # raise rules, not protocols, so that the bot can call the same code and
    # answer in words instead of in numbers.
    @app.exception_handler(errors.ServiceError)
    async def _service_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_for(exc), content={"detail": str(exc)})

    app.include_router(api_router)
    app.include_router(health_router)

    @app.post(settings.webhook_path, include_in_schema=False)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(default=""),
    ) -> Response:
        bot, dispatcher = request.app.state.bot, request.app.state.dispatcher
        if bot is None or dispatcher is None:
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

        expected = settings.webhook_secret
        if not expected:
            # Fail closed. With a token configured but no secret, an open
            # webhook lets anyone post a forged Update and make the bot speak
            # into any chat — so refuse to serve rather than skip the check.
            log.error("WEBHOOK_SECRET is unset; refusing webhook traffic")
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        # compare_digest rather than ==: the comparison must not leak how much
        # of the secret a guess got right.
        if not secrets.compare_digest(x_telegram_bot_api_secret_token, expected):
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)

        # context={"bot": bot} is required — without it the message shortcuts
        # (message.answer and friends) have no bot to call.
        update = Update.model_validate(await request.json(), context={"bot": bot})
        try:
            await dispatcher.feed_update(bot, update)
        except Exception:
            # 200 even so. Telegram reads any other status as "not delivered"
            # and redelivers the same update, so a handler that throws on one
            # message would have the webhook hammered with it until Telegram
            # gives up on the bot entirely. The update *was* received; the
            # failure is ours to see in the log, not Telegram's to retry.
            log.exception("handler failed for update %s", update.update_id)
        return Response(status_code=status.HTTP_200_OK)

    return app


app = create_app()
