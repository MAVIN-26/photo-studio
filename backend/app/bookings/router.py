from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.auth.dependencies import CsrfSession, fail, require_client
from app.auth.models import User
from app.bookings import service
from app.bookings.models import ScheduleEntry
from app.bookings.schemas import (
    Availability,
    BookingList,
    BookingResponse,
    BookingScope,
    BookingStatus,
    BookingVersion,
    ChangedBooking,
    CreateBooking,
    CreatedBooking,
    RescheduleBooking,
)
from app.bookings.service import (
    allowed_actions,
    availability,
    cancel_booking,
    check_action,
    create_booking,
    get_owned_booking,
    list_bookings,
    pay_booking,
    reschedule_booking,
)
from app.dependencies import Database
from app.rooms.service import get_room

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])
Client = Annotated[User, Depends(require_client)]


def booking_response(entry: ScheduleEntry) -> BookingResponse:
    result = BookingResponse.model_validate(entry)
    result.allowed_actions = allowed_actions(entry, service.studio_now())
    return result


def changed_response(entry: ScheduleEntry, message: str) -> ChangedBooking:
    return ChangedBooking(**booking_response(entry).model_dump(), message=message)


@router.post("", status_code=201, response_model=CreatedBooking)
def create(
    body: CreateBooking, user: Client, response: Response, db: Database, session: CsrfSession
):
    entry = create_booking(db, user.id, body)
    response.headers["Location"] = f"/api/v1/bookings/{entry.id}"
    return CreatedBooking(**booking_response(entry).model_dump())


@router.get("", response_model=BookingList)
def booking_list(
    user: Client,
    db: Database,
    scope: BookingScope = "all",
    status: BookingStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = list_bookings(
        db, user.id, scope=scope, status=status, limit=limit, offset=offset
    )
    return BookingList(
        items=[booking_response(entry) for entry in items], total=total, limit=limit, offset=offset
    )


@router.get("/{booking_id}", response_model=BookingResponse)
def booking_detail(booking_id: UUID, user: Client, db: Database):
    return booking_response(get_owned_booking(db, user.id, booking_id))


@router.get("/{booking_id}/availability", response_model=Availability)
def reschedule_availability(booking_id: UUID, date: date, user: Client, db: Database):
    entry = get_owned_booking(db, user.id, booking_id)
    check_action(entry, "reschedule", service.studio_now())
    room = get_room(db, entry.room_id)
    if room is None:
        fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
    return availability(db, room, date, exclude_booking_id=entry.id)


@router.post("/{booking_id}/pay", response_model=ChangedBooking)
def pay(booking_id: UUID, body: BookingVersion, user: Client, db: Database, session: CsrfSession):
    entry = pay_booking(db, user.id, booking_id, body.version)
    return changed_response(entry, "Бронь оплачена. Демонстрационная оплата выполнена.")


@router.post("/{booking_id}/cancel", response_model=ChangedBooking)
def cancel(
    booking_id: UUID, body: BookingVersion, user: Client, db: Database, session: CsrfSession
):
    entry = cancel_booking(db, user.id, booking_id, body.version)
    return changed_response(entry, "Бронь отменена. Время снова доступно.")


@router.post("/{booking_id}/reschedule", response_model=ChangedBooking)
def reschedule(
    booking_id: UUID, body: RescheduleBooking, user: Client, db: Database, session: CsrfSession
):
    entry = reschedule_booking(db, user.id, booking_id, body)
    return changed_response(entry, "Бронь перенесена.")
