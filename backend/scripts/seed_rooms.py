from datetime import time
from uuid import NAMESPACE_DNS, uuid5

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.database import create_database_engine
from app.rooms.models import Room

DEMO_ROOMS = (
    ("cyclorama", "Циклорама", 200_000),
    ("loft", "Лофт", 250_000),
    ("neon", "Неон", 180_000),
    ("scandi", "Сканди", 220_000),
)


def seed_rooms(engine: Engine) -> int:
    rooms = [
        {
            "id": uuid5(NAMESPACE_DNS, f"lumenbook.room.{slug}"),
            "name": name,
            "hourly_price_minor": price,
            "opens_at": time(9),
            "closes_at": time(23),
        }
        for slug, name, price in DEMO_ROOMS
    ]
    statement = insert(Room).values(rooms).on_conflict_do_nothing(index_elements=[Room.id])
    with engine.begin() as connection:
        result = connection.execute(statement.returning(Room.id))
        return len(result.all())


def main() -> None:
    engine = create_database_engine(get_settings())
    try:
        added = seed_rooms(engine)
        print(f"Добавлено залов: {added}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
