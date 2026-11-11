from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.auth.schemas import normalize_phone

BookingStatus = Literal["pending_payment", "paid", "confirmed", "cancelled"]
BookingScope = Literal["all", "upcoming", "past"]


class CreateBooking(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    room_id: UUID
    room_version: int = Field(ge=1, strict=True)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    contact_name: str = Field(min_length=1, max_length=100)
    contact_phone: str = Field(max_length=64)
    comment: str = Field(default="", max_length=1000)

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def require_timestamp_string(cls, value: object) -> object:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError("Укажите дату и время в ISO 8601 с часовым смещением")
        return value


class Slot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    available: bool


class Availability(BaseModel):
    room_id: UUID
    date: date
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    server_now: datetime
    room_version: int
    hourly_price_minor: int
    currency: Literal["RUB"] = "RUB"
    slots: list[Slot]


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    user_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    source: str
    contact_name: str
    contact_phone: str
    comment: str
    hourly_price_minor: int
    total_price_minor: int
    currency: Literal["RUB"] = "RUB"
    paid_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    allowed_actions: list[str] = Field(default_factory=list)


class CreatedBooking(BookingResponse):
    message: str = "Бронь создана. Время закреплено за вами."


class BookingList(BaseModel):
    items: list[BookingResponse]
    total: int
    limit: int
    offset: int
