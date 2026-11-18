from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.bookings.schemas import BookingResponse
from app.rooms.schemas import RoomResponse


class ScheduleBlock(BaseModel):
    id: UUID
    room_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: Literal["cleaning", "repair"]
    status: Literal["active"] = "active"
    version: int
    created_at: datetime
    updated_at: datetime


class AdminSchedule(BaseModel):
    date_from: date
    date_to: date
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    server_now: datetime
    rooms: list[RoomResponse]
    bookings: list[BookingResponse]
    blocks: list[ScheduleBlock]


class AdminBooking(BookingResponse):
    room_name: str
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None


class ChangedAdminBooking(AdminBooking):
    message: str
