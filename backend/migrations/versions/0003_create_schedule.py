"""Общий календарь и журнал событий."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint

revision = "0003_create_schedule"
down_revision = "0002_create_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "schedule_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("room_id", sa.Uuid(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("contact_name", sa.String(100)),
        sa.Column("contact_phone", sa.String(16)),
        sa.Column("comment", sa.String(1000)),
        sa.Column("hourly_price_minor", sa.Integer()),
        sa.Column("total_price_minor", sa.BigInteger()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("block_reason", sa.String(12)),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ends_at > starts_at ",
            name=op.f("ck_schedule_entries_positive_interval"),
        ),
        sa.CheckConstraint(
            "date_trunc('hour', starts_at AT TIME ZONE 'Europe/Moscow') = starts_at AT TIME ZONE "
            "'Europe/Moscow' AND date_trunc('hour', ends_at AT TIME ZONE 'Europe/Moscow') "
            "= ends_at AT TIME ZONE 'Europe/Moscow'",
            name=op.f("ck_schedule_entries_whole_hours"),
        ),
        sa.CheckConstraint(
            "CAST(starts_at AT TIME ZONE 'Europe/Moscow' AS date) = CAST(ends_at AT TIME ZONE "
            "'Europe/Moscow' AS date) ",
            name=op.f("ck_schedule_entries_single_day"),
        ),
        sa.CheckConstraint(
            "version > 0 ",
            name=op.f("ck_schedule_entries_positive_version"),
        ),
        sa.CheckConstraint(
            "( "
            "kind = 'booking' AND status IN ('pending_payment', 'paid', 'confirmed', 'cancelled') "
            "AND ((source = 'website' AND user_id IS NOT NULL AND user_id = created_by) "
            "OR (source IN ('phone', 'telegram', 'vk') AND user_id IS NULL)) "
            "AND contact_name IS NOT NULL AND length(trim(contact_name)) > 0 "
            "AND contact_phone IS NOT NULL AND comment IS NOT NULL "
            "AND hourly_price_minor IS NOT NULL AND hourly_price_minor > 0 "
            "AND total_price_minor IS NOT NULL "
            "AND total_price_minor = hourly_price_minor * "
            "(EXTRACT(EPOCH FROM ends_at - starts_at) / 3600) "
            "AND (status != 'paid' OR paid_at IS NOT NULL) AND block_reason IS NULL "
            ") OR ( "
            "kind = 'maintenance' AND status IN ('confirmed', 'cancelled') AND source = "
            "'maintenance' "
            "AND block_reason IS NOT NULL AND block_reason IN ('cleaning', 'repair') "
            "AND user_id IS NULL AND contact_name IS NULL AND contact_phone IS NULL AND comment IS "
            "NULL "
            "AND hourly_price_minor IS NULL AND total_price_minor IS NULL AND paid_at IS NULL "
            ") ",
            name=op.f("ck_schedule_entries_entry_fields"),
        ),
        ExcludeConstraint(
            ("room_id", "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text("status <> 'cancelled'"),
            using="gist",
            name="ex_schedule_entries_room_interval",
        ),
    )
    op.create_index(
        "ix_schedule_entries_owner_start", "schedule_entries", ["user_id", "starts_at", "id"]
    )
    op.create_table(
        "event_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entry_id", sa.Uuid(), sa.ForeignKey("schedule_entries.id")),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("payload", JSONB(), nullable=False),
    )
    op.create_index("ix_event_log_entry_id", "event_log", ["entry_id"])


def downgrade() -> None:
    op.drop_table("event_log")
    op.drop_table("schedule_entries")
