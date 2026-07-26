"""One process: the API, the bot webhook, and eventually the mini app's build.

Keeping them together is not laziness — it is what makes the origin rule work.
Since 20 July 2026 Telegram only allows Mini App API calls from the app's own
origin, so the page and the API it talks to have to be the same host anyway.
"""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress

from aiogram.types import Update
from fastapi import FastAPI, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from konnekt.api.v1.routes import health_router
from konnekt.api.v1.routes import router as api_router
from konnekt.bot import build_bot, build_dispatcher, configure
from konnekt.core.config import get_settings
from konnekt.db.session import dispose_engine

log = logging.getLogger("konnekt")


# Backoff for webhook registration: quick at first, because the usual cause is
# a DNS record that has just been created, then patient, because the other
# cause is Telegram itself and there is nothing to gain by hammering it.
WEBHOOK_RETRY_DELAYS = (5, 15, 60, 180, 300)


async def _register_webhook(app: FastAPI, bot, dispatcher, settings) -> None:
    """Point Telegram at us, and keep trying until it agrees."""
    url = f"{settings.public_base_url.rstrip('/')}{settings.webhook_path}"
    attempt = 0
    while True:
        try:
            await bot.set_webhook(
                url=url,
                secret_token=settings.webhook_secret,
                # Only the update types something actually handles, so Telegram
                # stops sending the rest.
                allowed_updates=dispatcher.resolve_used_update_types(),
                drop_pending_updates=True,
            )
            await configure(bot, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            attempt += 1
            delay = WEBHOOK_RETRY_DELAYS[min(attempt - 1, len(WEBHOOK_RETRY_DELAYS) - 1)]
            app.state.webhook_status = f"failed: {exc}"
            log.error("webhook not registered (attempt %s): %s", attempt, exc)
            await asyncio.sleep(delay)
        else:
            app.state.webhook_status = "ok"
            log.info("webhook set to %s", url)
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.bot = None
    app.state.dispatcher = None
    app.state.webhook_task = None
    app.state.webhook_status = "not configured"

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
                _register_webhook(app, bot, dispatcher, settings)
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
    if app.state.bot is not None:
        await app.state.dispatcher.emit_shutdown(
            bot=app.state.bot, dispatcher=app.state.dispatcher
        )
        # Without this the aiohttp session behind the bot leaks on reload.
        await app.state.bot.session.close()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
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
