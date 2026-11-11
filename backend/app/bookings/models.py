from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

OVERLAP_CONSTRAINT = "ex_schedule_entries_room_interval"


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"
    __table_args__ = (
        CheckConstraint(
            "ends_at > starts_at ",
            name="positive_interval",
        ),
        CheckConstraint(
            "date_trunc('hour', starts_at AT TIME ZONE 'Europe/Moscow') = starts_at AT TIME ZONE "
            "'Europe/Moscow' AND date_trunc('hour', ends_at AT TIME ZONE 'Europe/Moscow') "
            "= ends_at AT TIME ZONE 'Europe/Moscow'",
            name="whole_hours",
        ),
        CheckConstraint(
            "CAST(starts_at AT TIME ZONE 'Europe/Moscow' AS date) = CAST(ends_at AT TIME ZONE "
            "'Europe/Moscow' AS date) ",
            name="single_day",
        ),
        CheckConstraint(
            "version > 0 ",
            name="positive_version",
        ),
        CheckConstraint(
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
            name="entry_fields",
        ),
        ExcludeConstraint(
            ("room_id", "="),
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=text("status <> 'cancelled'"),
            using="gist",
            name=OVERLAP_CONSTRAINT,
        ),
        Index("ix_schedule_entries_owner_start", "user_id", "starts_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(12))
    contact_name: Mapped[str | None] = mapped_column(String(100))
    contact_phone: Mapped[str | None] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(String(1000))
    hourly_price_minor: Mapped[int | None]
    total_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    block_reason: Mapped[str | None] = mapped_column(String(12))
    version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("schedule_entries.id"), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB)
