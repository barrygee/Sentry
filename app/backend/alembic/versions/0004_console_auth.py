"""console password and session state (ADR-0010)

Creates `console_auth`, a single row holding the console password's argon2id
hash, the version counter that expires sessions when the password changes, and
the secret every session cookie is signed with.

The row is inserted here rather than lazily by the application, so no request
path has to handle "the row does not exist yet" — a state that would otherwise
be reachable exactly once per install, at the least convenient moment.

`password_hash` is NULL on creation, and that is the meaningful default: it
means no password is set and the console is open, which is what a fresh install
is documented to do (ADR-0010). It is not a migration that half-ran.

Replaces `SENTRY_AUTH_TOKEN`, which needed no schema because it lived in the
environment.

Revision ID: 0004_console_auth
Revises: 0003_device_notes_antenna
Create Date: 2026-08-09
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_console_auth"
down_revision: str | Sequence[str] | None = "0003_device_notes_antenna"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the single-row table and seed it with a fresh session secret."""
    console_auth = op.create_table(
        "console_auth",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("password_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("session_secret", sa.String(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ck_console_auth_single_row"),
    )

    # Generated per install, at migration time. Every Sentry therefore signs its
    # sessions with a different key, so a cookie minted by one is meaningless to
    # another — which matters because these are all called "sentry" on port 8000
    # and an operator may well run two.
    op.bulk_insert(
        console_auth,
        [
            {
                "id": 1,
                "password_hash": None,
                "password_version": 0,
                "session_secret": secrets.token_urlsafe(48),
                "updated_at": 0,
            }
        ],
    )


def downgrade() -> None:
    """Drop the table, discarding the password with it.

    Downgrading past this revision returns the console to being open to anyone
    who can reach it. That is the honest consequence of removing the table that
    holds the only credential — there is nowhere else for it to live.
    """
    op.drop_table("console_auth")
