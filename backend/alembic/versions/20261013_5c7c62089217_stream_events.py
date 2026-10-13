"""stream events

Revision ID: 5c7c62089217
Revises: aabcea9d3bb6
Create Date: 2026-10-13 12:27:37.399025+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5c7c62089217"
down_revision: str | None = "aabcea9d3bb6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stream_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_stream_events")),
    )
    op.create_index(
        op.f("ix_stream_events_week_start"), "stream_events", ["week_start"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stream_events_week_start"), table_name="stream_events")
    op.drop_table("stream_events")
