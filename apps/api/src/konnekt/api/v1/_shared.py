"""Helpers more than one domain module needs.

Deliberately small. A module that collects everything shared becomes the god
module this package was split out of, so the bar for adding to it is that a
second domain already needs the thing.
"""

from fastapi import HTTPException, status
from sqlalchemy import select


async def require_row(session, model, value: int | None, field: str) -> None:
    """Reject an unknown foreign key here rather than at the database.

    Without this a typo'd id surfaces as ForeignKeyViolation — a 500 that says
    nothing useful — instead of a 422 naming the field.
    """
    if value is None:
        return
    if await session.scalar(select(model.id).where(model.id == value)) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown {field}: {value}"
        )
