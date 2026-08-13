"""the operator-set fixed position this Sentry reports to Sentinel

Creates `sentry_location`, a single row holding a latitude/longitude the
operator types once. Sentinel reads it back through `GET /api/status` and
`GET /api/v1/sdrs` and plots the Pi on its map, so nobody has to tell Sentinel
separately where each Sentry is.

Seeded here rather than lazily, for the same reason `console_auth` and
`host_control_settings` are: a "the row does not exist yet" state would be
reachable exactly once per install, at the least convenient moment.

Both coordinates seed `NULL`, not `0`. Unset has to stay distinguishable from
a deliberate position, or every Sentry that has never been placed appears on
Sentinel's map at 0°N 0°E off the coast of Africa.

Revision ID: 0006_sentry_location
Revises: 0005_host_control_settings
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_sentry_location"
down_revision: str | Sequence[str] | None = "0005_host_control_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the single-row table and seed it with no position set."""
    sentry_location = op.create_table(
        "sentry_location",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ck_sentry_location_single_row"),
        sa.CheckConstraint(
            "latitude IS NULL OR (latitude >= -90.0 AND latitude <= 90.0)",
            name="ck_sentry_location_latitude_range",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR (longitude >= -180.0 AND longitude <= 180.0)",
            name="ck_sentry_location_longitude_range",
        ),
    )
    op.bulk_insert(
        sentry_location,
        [{"id": 1, "latitude": None, "longitude": None, "updated_at": 0}],
    )


def downgrade() -> None:
    """Drop the table. Sentry then reports no location and Sentinel stops plotting it."""
    op.drop_table("sentry_location")
