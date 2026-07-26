"""Operational tables: query log and moderation verdicts."""

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Interval,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from konnekt.db.base import Base, CreatedAtMixin, IdMixin
from konnekt.db.models.enums import (
    ContentLang,
    ModeratedEntity,
    ModerationVerdict,
    pg_enum,
)


class SearchQuery(IdMixin, CreatedAtMixin, Base):
    """Every free-text search, with what we made of it and how it went.

    This is the most valuable table in the schema and costs nothing to keep.
    Queries that returned zero results are a ranked list of what the catalog is
    missing, and raw text paired with the parse is the training data for making
    the parser better.
    """

    __tablename__ = "search_queries"

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[ContentLang | None] = mapped_column(pg_enum(ContentLang, "content_lang"))

    # What the parser extracted: {"subject_id": 42, "institution_id": 3,
    # "service_type": "exam_help", "deadline": "2026-02-14"}.
    parsed: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Whether the user then corrected our chips — the cheapest possible signal
    # that the parse was wrong.
    corrected: Mapped[dict | None] = mapped_column(JSONB)

    results_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    parser: Mapped[str | None] = mapped_column(String(64))
    took: Mapped[object | None] = mapped_column(Interval)

    __table_args__ = (
        Index("ix_search_queries_created", "created_at"),
        Index("ix_search_queries_empty", "results_count", "created_at"),
        Index("ix_search_queries_parsed", "parsed", postgresql_using="gin"),
    )


class ModerationReview(IdMixin, CreatedAtMixin, Base):
    """A verdict on one piece of user content.

    Generic on purpose: profiles, offers, requests, items and materials all pass
    through the same gate, and the gate may be a model, a human, or both.
    """

    __tablename__ = "moderation_reviews"

    entity_type: Mapped[ModeratedEntity] = mapped_column(
        pg_enum(ModeratedEntity, "moderated_entity"), nullable=False
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    verdict: Mapped[ModerationVerdict] = mapped_column(
        pg_enum(ModerationVerdict, "moderation_verdict"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    # Which model or which human produced this verdict.
    reviewer: Mapped[str | None] = mapped_column(String(96))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        Index("ix_moderation_reviews_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_moderation_reviews_queue", "verdict", "created_at"),
    )


__all__ = ["ModerationReview", "SearchQuery"]
