"""sdr visibility — publish a device to Sentinel, or keep it local

Adds `sdr_devices.visibility`, the per-device switch controlling whether a
device appears in `GET /api/v1/sdrs` (the Sentinel-consumed export). Existing
rows are backfilled to 'private' by the server default: an operator who
configured devices before this column existed never opted into publishing
them, so the upgrade must not start handing their IQ endpoints to any Sentinel
that asks. They opt in per device via the card's Public/Private toggle.

Revision ID: 0002_sdr_visibility
Revises: 0001_initial_fleet
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sdr_visibility"
down_revision: str | Sequence[str] | None = "0001_initial_fleet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `visibility` with its CHECK constraint, defaulting every row to 'private'."""
    # `batch_alter_table` per ADR-0005: SQLite cannot add a CHECK constraint to
    # an existing table in place, so the column and its constraint are added in
    # one batch (table copy) rather than two statements, the second of which
    # would fail.
    with op.batch_alter_table("sdr_devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("visibility", sa.String(), server_default="private", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_sdr_devices_visibility", "visibility IN ('public', 'private')"
        )


def downgrade() -> None:
    """Drop `visibility` and its CHECK constraint.

    Destructive in one narrow sense: which devices an operator chose to
    publish is forgotten, and re-upgrading returns every device to 'private'.
    No device configuration itself is lost.
    """
    with op.batch_alter_table("sdr_devices", schema=None) as batch_op:
        batch_op.drop_constraint("ck_sdr_devices_visibility", type_="check")
        batch_op.drop_column("visibility")
