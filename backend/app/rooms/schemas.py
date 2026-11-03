from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    image_url: str | None
    hourly_price_minor: int
    currency: Literal["RUB"] = "RUB"
    opens_at: time
    closes_at: time
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    version: int

    @field_serializer("opens_at", "closes_at")
    def serialize_time(self, value: time) -> str:
        return value.strftime("%H:%M")


class RoomListResponse(BaseModel):
    items: list[RoomResponse]
