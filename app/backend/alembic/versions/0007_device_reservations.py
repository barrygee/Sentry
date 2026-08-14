"""device reservations — a lease on a dongle held by whoever is using it

Creates `device_reservations`. A dongle is one physical resource with several
possible consumers (Sentinel's AIR view, its voice decoder, a second Sentinel,
an operator in this console), and until now any of them could retune it out from
under the others, leaving the loser silently decoding nothing.

Rows are keyed by `(identity_kind, identity_key)` — the same stable identity
`sdr_devices` uses (ADR-0003) — so a claim follows the physical dongle across a
replug, and a device with no configuration row yet can still be claimed. The
unique constraint is what makes two consumers racing for the same device a
failed write rather than a second row.

Nothing is seeded: no reservation is the correct initial state, and unlike the
single-row settings tables there is no "the row does not exist yet" case to
guard against — a device is simply unclaimed until something claims it.

Revision ID: 0007_device_reservations
Revises: 0006_sentry_location
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_device_reservations"
down_revision: str | Sequence[str] | None = "0006_sentry_location"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the reservations table."""
    op.create_table(
        "device_reservations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("identity_kind", sa.String(), nullable=False),
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("holder", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False, server_default=""),
        sa.Column("reserved_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "identity_kind", "identity_key", name="uq_device_reservations_identity"
        ),
    )
    # Expiry is read on every claim check — "is this lease still live?" is the
    # question the whole table exists to answer — and swept periodically.
    op.create_index("ix_device_reservations_expires_at", "device_reservations", ["expires_at"])


def downgrade() -> None:
    """Drop the table. Every device becomes unclaimed, and nothing enforces exclusivity."""
    op.drop_index("ix_device_reservations_expires_at", table_name="device_reservations")
    op.drop_table("device_reservations")
