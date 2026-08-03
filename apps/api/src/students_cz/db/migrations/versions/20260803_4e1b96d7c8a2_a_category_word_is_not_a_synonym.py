"""A category word is not a synonym of one member of it

`prijimacky` and `приймачки` sat in `subjects.synonyms` on «Поступление в
технические вузы», and a synonym scores 1.00 — so every «přijímačky …» query
came back filtered by maths and physics, including one that said medicine. The
word names a kind of help and reaches `entrance_prep` through the parser's
keyword table, which is where a category word belongs.

Here as well as in `seeds/subjects.json` because the deploy runs `alembic
upgrade head` and never the seed: production carries both synonyms today.

Revision ID: 4e1b96d7c8a2
Revises: c37f5a8e2b14
Create Date: 2026-08-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4e1b96d7c8a2"
down_revision: str | Sequence[str] | None = "c37f5a8e2b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SUBJECT = "prijimacky-technicke-vs"
WORDS = ("prijimacky", "приймачки")


def upgrade() -> None:
    bind = op.get_bind()
    for word in WORDS:
        bind.execute(
            sa.text(
                "UPDATE subjects SET synonyms = array_remove(synonyms, :word)"
                " WHERE slug = :slug"
            ),
            {"word": word, "slug": SUBJECT},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for word in WORDS:
        # Appended only when it is not already there, so a downgrade after a
        # re-seed does not leave the word twice.
        bind.execute(
            sa.text(
                "UPDATE subjects SET synonyms = synonyms || :word"
                " WHERE slug = :slug AND NOT (synonyms @> ARRAY[:word]::text[])"
            ),
            {"word": word, "slug": SUBJECT},
        )
