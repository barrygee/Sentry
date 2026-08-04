"""initial — create sdr_devices (architecture §6.1, §6.2)

Creates the single table Sentry persists: one row per operator-configured
RTL-SDR device, keyed by its resolved identity rather than USB enumeration
order. There is no data migration — the previous single-dongle deployment has
no database, so the one hard-wired dongle is re-registered through the UI, a
one-time operator action documented in the README.

**The `0001_initial_fleet` identifier deliberately keeps its original name**,
even though "fleet" is no longer this project's vocabulary. A revision id is
written verbatim into every deployment's `alembic_version` table; renaming it
would leave any Pi already running Sentry pointing at a revision that no longer
exists, and the next `alembic upgrade head` — which runs unattended on every
startup — would fail rather than no-op. The filename is kept in step with the id
for the same reason: so the two never have to be reconciled by hand.

Revision ID: 0001_initial_fleet
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_fleet"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create `sdr_devices` with both unique indexes and both CHECK constraints."""
    op.create_table(
        "sdr_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("identity_kind", sa.String(), nullable=False),
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), server_default="", nullable=False),
        sa.Column("output_port", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("center_hz", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("gain_db", sa.Float(), nullable=True),
        sa.Column("gain_auto", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("ppm_correction", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bias_tee", sa.Boolean(), nullable=True),
        sa.Column("direct_sampling", sa.Integer(), nullable=True),
        sa.Column("last_topology_path", sa.String(), server_default="", nullable=False),
        sa.Column("last_vendor_id", sa.String(), server_default="", nullable=False),
        sa.Column("last_product_id", sa.String(), server_default="", nullable=False),
        sa.Column("last_manufacturer", sa.String(), server_default="", nullable=False),
        sa.Column("last_product", sa.String(), server_default="", nullable=False),
        sa.Column("last_serial", sa.String(), server_default="", nullable=False),
        sa.Column("last_seen_at", sa.Integer(), nullable=True),
        sa.Column("pending_replug_until", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "identity_kind IN ('serial', 'usb')", name="ck_sdr_devices_identity_kind"
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 64", name="ck_sdr_devices_name_length"),
        sa.CheckConstraint(
            "output_port BETWEEN 1024 AND 65533", name="ck_sdr_devices_output_port_range"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # `batch_alter_table` (rather than a bare `create_index`) keeps this
    # migration consistent with `render_as_batch=True` (ADR-0005), so future
    # non-additive migrations on this table follow the same, tested pattern.
    with op.batch_alter_table("sdr_devices", schema=None) as batch_op:
        batch_op.create_index(
            "ux_sdr_devices_identity", ["identity_kind", "identity_key"], unique=True
        )
        batch_op.create_index("ux_sdr_devices_port", ["output_port"], unique=True)


def downgrade() -> None:
    """Drop `sdr_devices` and both of its unique indexes.

    Destructive: this discards every persisted device name, port assignment
    and tuning setting. Flagged here for explicit confirmation before running
    in any environment holding real configuration.
    """
    with op.batch_alter_table("sdr_devices", schema=None) as batch_op:
        batch_op.drop_index("ux_sdr_devices_port")
        batch_op.drop_index("ux_sdr_devices_identity")

    op.drop_table("sdr_devices")
