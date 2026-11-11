from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.auth.dependencies import CsrfSession, fail, require_client
from app.auth.models import User
from app.bookings.schemas import (
    BookingList,
    BookingResponse,
    BookingScope,
    BookingStatus,
    CreateBooking,
    CreatedBooking,
)
from app.bookings.service import create_booking, list_bookings, owned_booking
from app.dependencies import Database

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])
Client = Annotated[User, Depends(require_client)]


@router.post("", status_code=201, response_model=CreatedBooking)
def create(
    body: CreateBooking, user: Client, response: Response, db: Database, session: CsrfSession
):
    entry = create_booking(db, user.id, body)
    response.headers["Location"] = f"/api/v1/bookings/{entry.id}"
    return entry


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
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{booking_id}", response_model=BookingResponse)
def booking_detail(booking_id: UUID, user: Client, db: Database):
    entry = owned_booking(db, user.id, booking_id)
    if entry is None:
        fail(404, "BOOKING_NOT_FOUND", "Бронь не найдена.")
    return entry
