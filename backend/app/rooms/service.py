from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.rooms.models import Room

CATALOG_ORDER = ("Циклорама", "Лофт", "Неон", "Сканди")


def list_rooms(db: Session) -> list[Room]:
    position = case(
        {name: index for index, name in enumerate(CATALOG_ORDER)},
        value=Room.name,
        else_=len(CATALOG_ORDER),
    )
    return list(db.scalars(select(Room).order_by(position, Room.name, Room.id)))


def get_room(db: Session, room_id: UUID) -> Room | None:
    return db.get(Room, room_id)
