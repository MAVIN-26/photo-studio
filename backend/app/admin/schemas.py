import re
from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.bookings.schemas import (
    BookingInterval,
    BookingResponse,
    BookingStatus,
    BookingVersion,
    CreateBooking,
    ManualBookingSource,
)
from app.rooms.schemas import RoomResponse

BlockReason = Literal["cleaning", "repair"]


class ScheduleBlock(BaseModel):
    id: UUID
    room_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: BlockReason
    status: Literal["active", "cancelled"]
    version: int
    created_at: datetime
    updated_at: datetime


class CreateBlock(BookingInterval):
    model_config = ConfigDict(extra="forbid")

    room_id: UUID
    reason: BlockReason


class AdminSchedule(BaseModel):
    date_from: date
    date_to: date
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    server_now: datetime
    rooms: list[RoomResponse]
    bookings: list[BookingResponse]
    blocks: list[ScheduleBlock]


class AdminBookingFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    room_id: UUID | None = None
    status: BookingStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AdminBooking(BookingResponse):
    room_name: str
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None


class ChangedAdminBooking(AdminBooking):
    message: str


class CreateManualBooking(CreateBooking):
    source: ManualBookingSource


class RoomSettingsPatch(BookingVersion):
    hourly_price_minor: int | None = Field(default=None, gt=0, le=2_147_483_647, strict=True)
    opens_at: time | None = None
    closes_at: time | None = None

    @field_validator("hourly_price_minor", "opens_at", "closes_at", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Укажите значение поля")
        return value

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def validate_hour(cls, value: object) -> object:
        if not isinstance(value, str) or not re.fullmatch(r"(?:09|1[0-9]|2[0-3]):00", value):
            raise ValueError("Укажите целый час в диапазоне 09:00–23:00")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if self.model_fields_set == {"version"}:
            raise ValueError("Укажите цену или часы работы зала")
        return self
