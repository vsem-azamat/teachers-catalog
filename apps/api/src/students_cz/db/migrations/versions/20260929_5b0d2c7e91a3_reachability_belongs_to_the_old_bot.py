"""Reachability belongs to the old bot

`users.bot_started_at` recorded a /start sent to `@student_cz_bot`. The token
is now the moderator bot's (`@konnekt_moder_bot`), and a person who started
the old bot has not necessarily started this one. Left in place, their first
notification goes to a bot they never met, comes back as a 403, and is
recorded as a block. Cleared, they become reachable again on their next visit,
when the initData carries `allows_write_to_pm`. See docs/architecture.md.

`bot_can_message` goes back to its default for the same reason: a 403 from the
old bot says nothing about the new one.

The history stays in `user_events` (the BOT_START rows), so nothing that
happened is lost. The downgrade cannot restore the timestamps and does not try.

Revision ID: 5b0d2c7e91a3
Revises: 01b89b8f84b1
Create Date: 2026-09-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "5b0d2c7e91a3"
down_revision: str | Sequence[str] | None = "01b89b8f84b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET bot_started_at = NULL, bot_can_message = true "
        "WHERE bot_started_at IS NOT NULL OR bot_can_message IS NOT true"
    )


def downgrade() -> None:
    """Nothing to restore: the timestamps were about a bot we no longer run."""
