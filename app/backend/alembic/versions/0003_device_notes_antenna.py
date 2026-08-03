"""device notes and antenna — operator documentation fields

Adds `sdr_devices.notes` and `sdr_devices.antenna`: the operator's free-text
notes about a device and the antenna feeding it. Both are published in
`GET /api/v1/sdrs` for any device marked public, alongside every other
device field.

Both default to the empty string, so existing rows need no backfill.

Revision ID: 0003_device_notes_antenna
Revises: 0002_sdr_visibility
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_device_notes_antenna"
down_revision: str | Sequence[str] | None = "0002_sdr_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two free-text columns, both defaulting to ''."""
    # `batch_alter_table` per ADR-0005, consistent with the other migrations on
    # this table even though a plain `add_column` would suffice for SQLite here.
    with op.batch_alter_table("sdr_devices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notes", sa.String(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("antenna", sa.String(), server_default="", nullable=False))


def downgrade() -> None:
    """Drop both columns.

    Destructive: every operator note and antenna description is discarded.
    No device configuration or port assignment is affected.
    """
    with op.batch_alter_table("sdr_devices", schema=None) as batch_op:
        batch_op.drop_column("antenna")
        batch_op.drop_column("notes")
