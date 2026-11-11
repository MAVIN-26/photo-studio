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
    RescheduleBooking,
    Slot,
)
from app.rooms.models import Room

STUDIO_ZONE = ZoneInfo("Europe/Moscow")
BOOKING_HORIZON = timedelta(days=30)
HOUR = timedelta(hours=1)
CHANGE_DEADLINE = timedelta(hours=24)


def studio_now() -> datetime:
    return datetime.now(STUDIO_ZONE)


def validate_booking_day(day: date, now: datetime) -> None:
    if not now.date() <= day <= now.date() + BOOKING_HORIZON:
        fail(422, "DATE_OUT_OF_RANGE", "Выберите дату в пределах 30 дней от сегодняшней.")


def availability(
    db: Session, room: Room, day: date, *, exclude_booking_id: UUID | None = None
) -> Availability:
    now = studio_now()
    validate_booking_day(day, now)
    opens = datetime.combine(day, room.opens_at, STUDIO_ZONE)
    closes = datetime.combine(day, room.closes_at, STUDIO_ZONE)
    query = select(ScheduleEntry.starts_at, ScheduleEntry.ends_at).where(
        ScheduleEntry.room_id == room.id,
        ScheduleEntry.status != "cancelled",
        ScheduleEntry.starts_at < closes,
        ScheduleEntry.ends_at > opens,
    )
    if exclude_booking_id is not None:
        query = query.where(ScheduleEntry.id != exclude_booking_id)
    occupied = db.execute(query).all()
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


def validate_interval(
    room: Room, starts_at: datetime, ends_at: datetime, now: datetime
) -> tuple[datetime, datetime]:
    try:
        starts_at = starts_at.astimezone(STUDIO_ZONE)
        ends_at = ends_at.astimezone(STUDIO_ZONE)
    except OverflowError:
        fail(422, "INVALID_TIME_RANGE", "Укажите допустимый интервал.")
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
    return starts_at, ends_at


def lock_room(db: Session, room_id: UUID) -> Room:
    room = db.scalar(select(Room).where(Room.id == room_id).with_for_update())
    if room is None:
        fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
    return room


def create_booking(db: Session, user_id: UUID, body: CreateBooking) -> ScheduleEntry:
    room = lock_room(db, body.room_id)
    if body.room_version != room.version:
        fail(409, "ROOM_SETTINGS_CHANGED", "Условия зала изменились. Проверьте цену и время.")

    starts_at, ends_at = validate_interval(room, body.starts_at, body.ends_at, studio_now())
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
    commit_booking_event(db, entry, user_id, "booking_created", {})
    return entry


def commit_booking_event(
    db: Session, entry: ScheduleEntry, user_id: UUID, event_type: str, payload: dict
) -> None:
    try:
        db.flush()
        db.add_all(
            [
                EventLog(
                    entry_id=entry.id, actor_id=user_id, event_type=event_type, payload=payload
                ),
                EventLog(
                    entry_id=entry.id,
                    actor_id=user_id,
                    event_type="notification_simulated",
                    payload={"trigger": event_type},
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


def owned_booking(
    db: Session, user_id: UUID, booking_id: UUID, *, lock: bool = False
) -> ScheduleEntry | None:
    query = select(ScheduleEntry).where(
        ScheduleEntry.id == booking_id,
        ScheduleEntry.kind == "booking",
        ScheduleEntry.user_id == user_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def get_owned_booking(
    db: Session, user_id: UUID, booking_id: UUID, *, lock: bool = False
) -> ScheduleEntry:
    entry = owned_booking(db, user_id, booking_id, lock=lock)
    if entry is None:
        fail(404, "BOOKING_NOT_FOUND", "Бронь не найдена.")
    return entry


def allowed_actions(entry: ScheduleEntry, now: datetime) -> list[str]:
    actions = []
    if entry.status == "pending_payment" and entry.starts_at > now:
        actions.append("pay")
    if entry.status != "cancelled" and entry.starts_at - now >= CHANGE_DEADLINE:
        actions.extend(("cancel", "reschedule"))
    return actions


def check_action(entry: ScheduleEntry, action: str, now: datetime) -> None:
    if action in allowed_actions(entry, now):
        return
    if entry.status != "cancelled" and action == "cancel":
        fail(409, "CANCELLATION_DEADLINE_PASSED", "До начала брони осталось меньше 24 часов.")
    if entry.status != "cancelled" and action == "reschedule":
        fail(409, "RESCHEDULE_DEADLINE_PASSED", "До начала брони осталось меньше 24 часов.")
    fail(409, "INVALID_BOOKING_STATE", "Действие недоступно для этой брони.")


def lock_booking(
    db: Session, user_id: UUID, booking_id: UUID, version: int
) -> tuple[Room, ScheduleEntry]:
    entry = get_owned_booking(db, user_id, booking_id)
    room = lock_room(db, entry.room_id)
    entry = get_owned_booking(db, user_id, booking_id, lock=True)
    if entry.version != version:
        fail(409, "VERSION_CONFLICT", "Бронь изменилась. Проверьте её актуальные данные.")
    return room, entry


def pay_booking(db: Session, user_id: UUID, booking_id: UUID, version: int) -> ScheduleEntry:
    _, entry = lock_booking(db, user_id, booking_id, version)
    now = studio_now()
    check_action(entry, "pay", now)
    entry.status = "paid"
    entry.paid_at = now
    entry.version += 1
    commit_booking_event(db, entry, user_id, "booking_paid", {})
    return entry


def cancel_booking(db: Session, user_id: UUID, booking_id: UUID, version: int) -> ScheduleEntry:
    _, entry = lock_booking(db, user_id, booking_id, version)
    check_action(entry, "cancel", studio_now())
    entry.status = "cancelled"
    entry.version += 1
    commit_booking_event(db, entry, user_id, "booking_cancelled", {})
    return entry


def reschedule_booking(
    db: Session, user_id: UUID, booking_id: UUID, body: RescheduleBooking
) -> ScheduleEntry:
    room, entry = lock_booking(db, user_id, booking_id, body.version)
    now = studio_now()
    check_action(entry, "reschedule", now)
    starts_at, ends_at = validate_interval(room, body.starts_at, body.ends_at, now)
    if ends_at - starts_at != entry.ends_at - entry.starts_at:
        fail(422, "DURATION_CHANGE_NOT_ALLOWED", "Длительность брони должна сохраниться.")
    previous_interval = {
        "starts_at": entry.starts_at.isoformat(),
        "ends_at": entry.ends_at.isoformat(),
    }
    entry.starts_at = starts_at
    entry.ends_at = ends_at
    entry.version += 1
    commit_booking_event(
        db,
        entry,
        user_id,
        "booking_rescheduled",
        {
            "previous": previous_interval,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        },
    )
    return entry


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
