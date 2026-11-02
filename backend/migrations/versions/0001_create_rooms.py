"""Создание таблицы залов."""

import sqlalchemy as sa
from alembic import op

revision = "0001_create_rooms"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("hourly_price_minor", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_rooms_name_not_blank")),
        sa.CheckConstraint("hourly_price_minor > 0", name=op.f("ck_rooms_price_positive")),
        sa.CheckConstraint("version > 0", name=op.f("ck_rooms_version_positive")),
        sa.CheckConstraint(
            "opens_at >= TIME '09:00' AND closes_at <= TIME '23:00' AND opens_at < closes_at",
            name=op.f("ck_rooms_working_hours"),
        ),
        sa.CheckConstraint(
            "EXTRACT(MINUTE FROM opens_at) = 0 AND EXTRACT(SECOND FROM opens_at) = 0 "
            "AND EXTRACT(MINUTE FROM closes_at) = 0 AND EXTRACT(SECOND FROM closes_at) = 0",
            name=op.f("ck_rooms_whole_hours"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
        sa.UniqueConstraint("name", name=op.f("uq_rooms_name")),
    )


def downgrade() -> None:
    op.drop_table("rooms")
