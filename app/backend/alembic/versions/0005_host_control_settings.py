"""operator-controlled host capability switches (ADR-0013)

Creates `host_control_settings`, a single row holding the switches that used to
be deploy-time `.env` gates. Only `hotspot_control_enabled` so far.

Seeded here rather than lazily, for the same reason `console_auth` is: a "the
row does not exist yet" state would be reachable exactly once per install, at
the least convenient moment.

It seeds `False` unconditionally — deliberately *not* carrying over whatever
`SENTRY_HOTSPOT_CONTROL_ENABLED` currently says. A migration cannot read the
container's environment reliably (it runs wherever `alembic` is invoked), and
guessing wrong in the permissive direction would silently switch on host
network control on somebody's Pi. The `.env` setting keeps working as an
override regardless (ADR-0013), so an operator who set it stays enabled without
this row's help.

Revision ID: 0005_host_control_settings
Revises: 0004_console_auth
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_host_control_settings"
down_revision: str | Sequence[str] | None = "0004_console_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the single-row table and seed it switched off."""
    host_control_settings = op.create_table(
        "host_control_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hotspot_control_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ck_host_control_settings_single_row"),
    )
    op.bulk_insert(
        host_control_settings,
        [{"id": 1, "hotspot_control_enabled": False, "updated_at": 0}],
    )


def downgrade() -> None:
    """Drop the table, returning control of the hotspot gate to `.env` alone."""
    op.drop_table("host_control_settings")
