from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import Time, cast, func, or_, select
from sqlalchemy.orm import Session

from app.admin.schemas import (
    AdminBooking,
    AdminSchedule,
    CreateManualBooking,
    RoomSettingsPatch,
    ScheduleBlock,
)
from app.auth.dependencies import fail
from app.bookings import service
from app.bookings.models import EventLog, ScheduleEntry
from app.bookings.schemas import Availability, BookingResponse, RescheduleBooking
from app.rooms.models import Room
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
            response = BookingResponse.model_validate(entry)
            response.allowed_actions = admin_actions(entry)
            bookings.append(response)
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


def read_booking(db: Session, booking_id: UUID, *, lock: bool = False) -> ScheduleEntry:
    query = select(ScheduleEntry).where(
        ScheduleEntry.id == booking_id, ScheduleEntry.kind == "booking"
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    entry = db.scalar(query)
    if entry is None:
        fail(404, "BOOKING_NOT_FOUND", "Бронь не найдена.")
    return entry


def admin_actions(entry: ScheduleEntry) -> list[str]:
    if entry.status == "cancelled":
        return []
    actions = ["cancel", "reschedule"]
    if entry.status == "paid":
        actions.insert(0, "confirm")
    return actions


def admin_booking_response(db: Session, entry: ScheduleEntry) -> AdminBooking:
    room = get_room(db, entry.room_id)
    if room is None:
        fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
    event_types = ("booking_confirmed", "booking_cancelled")
    events = db.execute(
        select(EventLog.event_type, EventLog.created_at)
        .where(EventLog.entry_id == entry.id, EventLog.event_type.in_(event_types))
        .order_by(EventLog.created_at, EventLog.id)
    )
    timestamps = {event_type: created_at for event_type, created_at in events}
    result = BookingResponse.model_validate(entry)
    result.allowed_actions = admin_actions(entry)
    return AdminBooking(
        **result.model_dump(),
        room_name=room.name,
        confirmed_at=timestamps.get("booking_confirmed"),
        cancelled_at=timestamps.get("booking_cancelled"),
    )


def check_admin_action(entry: ScheduleEntry, action: str) -> None:
    if action not in admin_actions(entry):
        fail(409, "INVALID_BOOKING_STATE", "Действие недоступно для этой брони.")


def lock_admin_booking(
    db: Session, booking_id: UUID, version: int, action: str
) -> tuple[Room, ScheduleEntry]:
    entry = read_booking(db, booking_id)
    room = service.lock_room(db, entry.room_id)
    entry = read_booking(db, booking_id, lock=True)
    service.check_booking_version(entry, version)
    check_admin_action(entry, action)
    return room, entry


def confirm_booking(db: Session, booking_id: UUID, version: int, actor_id: UUID) -> ScheduleEntry:
    _, entry = lock_admin_booking(db, booking_id, version, "confirm")
    entry.status = "confirmed"
    entry.version += 1
    service.commit_booking_event(db, entry, actor_id, "booking_confirmed", {})
    return entry


def cancel_booking(db: Session, booking_id: UUID, version: int, actor_id: UUID) -> ScheduleEntry:
    _, entry = lock_admin_booking(db, booking_id, version, "cancel")
    service.cancel_entry(db, entry, actor_id)
    return entry


def reschedule_booking(
    db: Session, booking_id: UUID, body: RescheduleBooking, actor_id: UUID
) -> ScheduleEntry:
    room, entry = lock_admin_booking(db, booking_id, body.version, "reschedule")
    service.move_entry(db, room, entry, actor_id, body, service.studio_now())
    return entry


def reschedule_availability(db: Session, booking_id: UUID, day: date) -> Availability:
    entry = read_booking(db, booking_id)
    check_admin_action(entry, "reschedule")
    room = get_room(db, entry.room_id)
    if room is None:
        fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
    return service.availability(db, room, day, exclude_booking_id=entry.id)


def create_manual_booking(db: Session, actor_id: UUID, body: CreateManualBooking) -> ScheduleEntry:
    return service.create_booking(db, actor_id, body, source=body.source)


def update_room_settings(
    db: Session, room_id: UUID, body: RoomSettingsPatch, actor_id: UUID
) -> Room:
    room = service.lock_room(db, room_id)
    if body.version != room.version:
        fail(409, "VERSION_CONFLICT", "Настройки зала изменились в другой вкладке.")

    opens_at = body.opens_at if body.opens_at is not None else room.opens_at
    closes_at = body.closes_at if body.closes_at is not None else room.closes_at
    if opens_at >= closes_at:
        fail(422, "INVALID_TIME_RANGE", "Время открытия должно быть раньше времени закрытия.")

    if opens_at > room.opens_at or closes_at < room.closes_at:
        conflict = db.scalar(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.room_id == room.id,
                ScheduleEntry.status != "cancelled",
                ScheduleEntry.ends_at > service.studio_now(),
                or_(
                    cast(func.timezone(service.STUDIO_ZONE.key, ScheduleEntry.starts_at), Time)
                    < opens_at,
                    cast(func.timezone(service.STUDIO_ZONE.key, ScheduleEntry.ends_at), Time)
                    > closes_at,
                ),
            )
            .order_by(ScheduleEntry.starts_at, ScheduleEntry.id)
            .limit(1)
        )
        if conflict is not None:
            start = conflict.starts_at.astimezone(service.STUDIO_ZONE)
            end = conflict.ends_at.astimezone(service.STUDIO_ZONE)
            record = "блокировка" if conflict.kind == "maintenance" else "бронь"
            fail(
                409,
                "ROOM_SCHEDULE_CONFLICT",
                f"Вне новых часов окажется {record} {start:%d.%m.%Y} "
                f"с {start:%H:%M} до {end:%H:%M} МСК.",
            )

    previous = RoomResponse.model_validate(room).model_dump(mode="json")
    changes = {
        field: value
        for field, value in body.model_dump(exclude_unset=True, exclude={"version"}).items()
        if value != getattr(room, field)
    }
    if changes:
        for field, value in changes.items():
            setattr(room, field, value)
        room.version += 1
        current = RoomResponse.model_validate(room).model_dump(mode="json")
        db.add(
            EventLog(
                actor_id=actor_id,
                event_type="room_settings_changed",
                payload={
                    "room_id": str(room.id),
                    "before": {field: previous[field] for field in changes},
                    "after": {field: current[field] for field in changes},
                },
            )
        )
    db.commit()
    return room
