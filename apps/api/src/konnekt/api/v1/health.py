"""Liveness, and the two things that fail independently of it.

Its own router with no prefix: `/healthz` is not part of the versioned API and
must not move when the API version does.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select

from konnekt.api.deps import SessionDep

_STARTED_AT = datetime.now(UTC)

health_router = APIRouter(tags=["ops"])


@health_router.get("/healthz")
async def healthz(request: Request, session: SessionDep) -> dict[str, str | int]:
    """Liveness plus the two things that fail independently.

    A webhook that never registered leaves the catalog perfectly usable and the
    bot deaf, which is exactly the kind of half-failure nobody notices. It is
    reported here rather than folded into the status, because taking the whole
    service out of rotation over it would be worse.
    """
    await session.execute(select(1))
    uptime = datetime.now(UTC) - _STARTED_AT
    return {
        "status": "ok",
        "database": "ok",
        "webhook": getattr(request.app.state, "webhook_status", "unknown"),
        "uptime_seconds": int(uptime / timedelta(seconds=1)),
    }
