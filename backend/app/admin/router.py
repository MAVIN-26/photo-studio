from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends

from app.admin.schemas import AdminSchedule
from app.admin.service import read_booking, read_schedule
from app.auth.dependencies import require_admin
from app.bookings.schemas import BookingResponse
from app.dependencies import Database

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/schedule", response_model=AdminSchedule)
def schedule(date_from: date, date_to: date, db: Database, room_id: UUID | None = None):
    return read_schedule(db, date_from, date_to, room_id)


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
def booking_detail(booking_id: UUID, db: Database):
    return read_booking(db, booking_id)
