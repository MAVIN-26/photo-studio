from datetime import datetime, time
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, Time, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("hourly_price_minor > 0", name="price_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "opens_at >= TIME '09:00' AND closes_at <= TIME '23:00' AND opens_at < closes_at",
            name="working_hours",
        ),
        CheckConstraint(
            "EXTRACT(MINUTE FROM opens_at) = 0 AND EXTRACT(SECOND FROM opens_at) = 0 "
            "AND EXTRACT(MINUTE FROM closes_at) = 0 AND EXTRACT(SECOND FROM closes_at) = 0",
            name="whole_hours",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_url: Mapped[str | None] = mapped_column(String(500))
    hourly_price_minor: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
