"""Дополнительные изображения залов."""

import sqlalchemy as sa
from alembic import op

revision = "0004_room_gallery"
down_revision = "0003_create_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column(
            "gallery_images",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rooms", "gallery_images")
