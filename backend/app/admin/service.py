from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.schemas import AdminSchedule, ScheduleBlock
from app.auth.dependencies import fail
from app.bookings import service
from app.bookings.models import ScheduleEntry
from app.bookings.schemas import BookingResponse
from app.rooms.schemas import RoomResponse
from app.rooms.service import get_room, list_rooms


def read_schedule(
    db: Session, date_from: date, date_to: date, room_id: UUID | None = None
) -> AdminSchedule:
    if not 0 <= (date_to - date_from).days <= 6 or date_to == date.max:
        fail(422, "DATE_OUT_OF_RANGE", "Укажите диапазон от одного до семи дней.")
    if room_id is None:
        rooms = list_rooms(db)
    else:
        room = get_room(db, room_id)
        if room is None:
            fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
        rooms = [room]

    start = datetime.combine(date_from, time.min, service.STUDIO_ZONE)
    end = datetime.combine(date_to + timedelta(days=1), time.min, service.STUDIO_ZONE)
    entries = db.scalars(
        select(ScheduleEntry)
        .where(
            ScheduleEntry.room_id.in_([room.id for room in rooms]),
            ScheduleEntry.status != "cancelled",
            ScheduleEntry.starts_at < end,
            ScheduleEntry.ends_at > start,
        )
        .order_by(ScheduleEntry.starts_at, ScheduleEntry.id)
    )
    bookings = []
    blocks = []
    for entry in entries:
        if entry.kind == "booking":
            bookings.append(BookingResponse.model_validate(entry))
        else:
            blocks.append(
                ScheduleBlock(
                    id=entry.id,
                    room_id=entry.room_id,
                    starts_at=entry.starts_at,
                    ends_at=entry.ends_at,
                    reason=entry.block_reason,
                    version=entry.version,
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                )
            )
    return AdminSchedule(
        date_from=date_from,
        date_to=date_to,
        server_now=service.studio_now(),
        rooms=[RoomResponse.model_validate(room) for room in rooms],
        bookings=bookings,
        blocks=blocks,
    )


def read_booking(db: Session, booking_id: UUID) -> ScheduleEntry:
    entry = db.get(ScheduleEntry, booking_id)
    if entry is None or entry.kind != "booking":
        fail(404, "BOOKING_NOT_FOUND", "Бронь не найдена.")
    return entry
