from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import fail
from app.bookings.models import OVERLAP_CONSTRAINT, EventLog, ScheduleEntry
from app.bookings.schemas import (
    Availability,
    BookingScope,
    BookingStatus,
    CreateBooking,
    Slot,
)
from app.rooms.models import Room

STUDIO_ZONE = ZoneInfo("Europe/Moscow")
BOOKING_HORIZON = timedelta(days=30)
HOUR = timedelta(hours=1)


def studio_now() -> datetime:
    return datetime.now(STUDIO_ZONE)


def validate_booking_day(day: date, now: datetime) -> None:
    if not now.date() <= day <= now.date() + BOOKING_HORIZON:
        fail(422, "DATE_OUT_OF_RANGE", "Выберите дату в пределах 30 дней от сегодняшней.")


def availability(db: Session, room: Room, day: date) -> Availability:
    now = studio_now()
    validate_booking_day(day, now)
    opens = datetime.combine(day, room.opens_at, STUDIO_ZONE)
    closes = datetime.combine(day, room.closes_at, STUDIO_ZONE)
    occupied = db.execute(
        select(ScheduleEntry.starts_at, ScheduleEntry.ends_at).where(
            ScheduleEntry.room_id == room.id,
            ScheduleEntry.status != "cancelled",
            ScheduleEntry.starts_at < closes,
            ScheduleEntry.ends_at > opens,
        )
    ).all()
    slots = []
    starts_at = opens
    while starts_at < closes:
        ends_at = starts_at + HOUR
        slots.append(
            Slot(
                starts_at=starts_at,
                ends_at=ends_at,
                available=starts_at > now
                and not any(start < ends_at and end > starts_at for start, end in occupied),
            )
        )
        starts_at = ends_at
    return Availability(
        room_id=room.id,
        date=day,
        server_now=now,
        room_version=room.version,
        hourly_price_minor=room.hourly_price_minor,
        slots=slots,
    )


def create_booking(db: Session, user_id: UUID, body: CreateBooking) -> ScheduleEntry:
    room = db.scalar(select(Room).where(Room.id == body.room_id).with_for_update())
    if room is None:
        fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
    if body.room_version != room.version:
        fail(409, "ROOM_SETTINGS_CHANGED", "Условия зала изменились. Проверьте цену и время.")

    now = studio_now()
    starts_at = body.starts_at.astimezone(STUDIO_ZONE)
    ends_at = body.ends_at.astimezone(STUDIO_ZONE)
    validate_booking_day(starts_at.date(), now)
    if (
        starts_at <= now
        or ends_at - starts_at < HOUR
        or starts_at.date() != ends_at.date()
        or any(value.minute or value.second or value.microsecond for value in (starts_at, ends_at))
        or starts_at.time() < room.opens_at
        or ends_at.time() > room.closes_at
    ):
        fail(422, "INVALID_TIME_RANGE", "Выберите целые будущие часы в пределах работы зала.")

    hours = (ends_at - starts_at) // HOUR
    entry = ScheduleEntry(
        room_id=room.id,
        starts_at=starts_at,
        ends_at=ends_at,
        kind="booking",
        status="pending_payment",
        user_id=user_id,
        created_by=user_id,
        source="website",
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        comment=body.comment,
        hourly_price_minor=room.hourly_price_minor,
        total_price_minor=room.hourly_price_minor * hours,
    )
    db.add(entry)
    try:
        db.flush()
        db.add_all(
            [
                EventLog(
                    entry_id=entry.id, actor_id=user_id, event_type="booking_created", payload={}
                ),
                EventLog(
                    entry_id=entry.id,
                    actor_id=user_id,
                    event_type="notification_simulated",
                    payload={"trigger": "booking_created"},
                ),
            ]
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if (
            getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            == OVERLAP_CONSTRAINT
        ):
            fail(409, "SLOT_UNAVAILABLE", "Это время уже заняли. Выберите другое время.")
        raise
    return entry


def owned_booking(db: Session, user_id: UUID, booking_id: UUID) -> ScheduleEntry | None:
    return db.scalar(
        select(ScheduleEntry).where(
            ScheduleEntry.id == booking_id,
            ScheduleEntry.kind == "booking",
            ScheduleEntry.user_id == user_id,
        )
    )


def list_bookings(
    db: Session,
    user_id: UUID,
    *,
    scope: BookingScope,
    status: BookingStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[ScheduleEntry], int]:
    filters = [ScheduleEntry.user_id == user_id, ScheduleEntry.kind == "booking"]
    if scope == "upcoming":
        filters.append(ScheduleEntry.starts_at > studio_now())
    elif scope == "past":
        filters.append(ScheduleEntry.ends_at <= studio_now())
    if status is not None:
        filters.append(ScheduleEntry.status == status)
    total = db.scalar(select(func.count()).select_from(ScheduleEntry).where(*filters)) or 0
    items = db.scalars(
        select(ScheduleEntry)
        .where(*filters)
        .order_by(ScheduleEntry.starts_at, ScheduleEntry.id)
        .limit(limit)
        .offset(offset)
    )
    return list(items), total
