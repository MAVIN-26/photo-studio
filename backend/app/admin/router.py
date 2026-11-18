from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.admin import service
from app.admin.schemas import AdminBooking, AdminSchedule, ChangedAdminBooking, CreateManualBooking
from app.auth.dependencies import CsrfSession, require_admin
from app.auth.models import User
from app.bookings.schemas import Availability, BookingVersion, RescheduleBooking
from app.dependencies import Database

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])
Admin = Annotated[User, Depends(require_admin)]


@router.get("/schedule", response_model=AdminSchedule)
def schedule(date_from: date, date_to: date, db: Database, room_id: UUID | None = None):
    return service.read_schedule(db, date_from, date_to, room_id)


@router.get("/bookings/{booking_id}", response_model=AdminBooking)
def booking_detail(booking_id: UUID, db: Database):
    return service.admin_booking_response(db, service.read_booking(db, booking_id))


@router.post("/bookings", status_code=201, response_model=ChangedAdminBooking)
def create(
    body: CreateManualBooking, admin: Admin, db: Database, csrf: CsrfSession, response: Response
):
    entry = service.create_manual_booking(db, admin.id, body)
    response.headers["Location"] = f"/api/v1/admin/bookings/{entry.id}"
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь создана."
    )


@router.get("/bookings/{booking_id}/availability", response_model=Availability)
def booking_availability(booking_id: UUID, date: date, db: Database):
    return service.reschedule_availability(db, booking_id, date)


@router.post("/bookings/{booking_id}/confirm", response_model=ChangedAdminBooking)
def confirm(booking_id: UUID, body: BookingVersion, admin: Admin, db: Database, csrf: CsrfSession):
    entry = service.confirm_booking(db, booking_id, body.version, admin.id)
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь подтверждена."
    )


@router.post("/bookings/{booking_id}/cancel", response_model=ChangedAdminBooking)
def cancel(booking_id: UUID, body: BookingVersion, admin: Admin, db: Database, csrf: CsrfSession):
    entry = service.cancel_booking(db, booking_id, body.version, admin.id)
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь отменена."
    )


@router.post("/bookings/{booking_id}/reschedule", response_model=ChangedAdminBooking)
def reschedule(
    booking_id: UUID, body: RescheduleBooking, admin: Admin, db: Database, csrf: CsrfSession
):
    entry = service.reschedule_booking(db, booking_id, body, admin.id)
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь перенесена."
    )
