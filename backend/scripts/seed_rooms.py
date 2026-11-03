from datetime import time
from uuid import NAMESPACE_DNS, uuid5

from sqlalchemy import Engine, update
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.database import create_database_engine
from app.rooms.models import Room

DEMO_ROOMS = (
    (
        "cyclorama",
        "Циклорама",
        200_000,
        "Белая бесшовная циклорама. Площадь 70 м², потолки 5 м, постоянный и импульсный свет.",
    ),
    (
        "loft",
        "Лофт",
        250_000,
        "Кирпичные стены, большие окна, дневной свет. "
        "Площадь 60 м², потолки 4 м, кожаный диван и винтажный реквизит.",
    ),
    (
        "neon",
        "Неон",
        180_000,
        "Тёмный зал с неоновой подсветкой. Площадь 45 м², RGB-подсветка, зеркальный пол.",
    ),
    (
        "scandi",
        "Сканди",
        220_000,
        "Светлый скандинавский интерьер. Площадь 50 м², мебель из дерева и живые растения.",
    ),
)


def seed_rooms(engine: Engine) -> int:
    rooms = [
        {
            "id": uuid5(NAMESPACE_DNS, f"lumenbook.room.{slug}"),
            "name": name,
            "hourly_price_minor": price,
            "description": description,
            "image_url": f"/static/rooms/{slug}.svg",
            "opens_at": time(9),
            "closes_at": time(23),
        }
        for slug, name, price, description in DEMO_ROOMS
    ]
    statement = insert(Room).values(rooms).on_conflict_do_nothing(index_elements=[Room.id])
    with engine.begin() as connection:
        result = connection.execute(statement.returning(Room.id))
        added = len(result.all())
        for room in rooms:
            for field in ("description", "image_url"):
                column = getattr(Room, field)
                missing = column == "" if field == "description" else column.is_(None)
                connection.execute(
                    update(Room).where(Room.id == room["id"], missing).values({field: room[field]})
                )
        return added


def main() -> None:
    engine = create_database_engine(get_settings())
    try:
        added = seed_rooms(engine)
        print(f"Добавлено залов: {added}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
