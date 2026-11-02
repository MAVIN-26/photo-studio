from datetime import time
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.rooms.models import Room
from scripts.seed_rooms import seed_rooms


def test_migrations_and_seed_preserve_edited_data(database):
    engine, _, config = database
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)

    assert seed_rooms(engine) == 4
    with engine.begin() as connection:
        rows = connection.execute(select(Room.name, Room.hourly_price_minor)).all()
        assert dict(rows) == {
            "Циклорама": 200_000,
            "Лофт": 250_000,
            "Неон": 180_000,
            "Сканди": 220_000,
        }
        connection.execute(
            update(Room).where(Room.name == "Лофт").values(hourly_price_minor=300_000)
        )

    assert seed_rooms(engine) == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(select(Room.hourly_price_minor).where(Room.name == "Лофт")) == 300_000
        )
        assert len(connection.execute(select(Room.id)).all()) == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"hourly_price_minor": 0},
        {"hourly_price_minor": -1},
        {"opens_at": time(8)},
        {"closes_at": time(23, 30)},
        {"opens_at": time(10, 30)},
        {"opens_at": time(12), "closes_at": time(12)},
        {"version": 0},
        {"name": "   "},
    ],
)
def test_room_constraints_reject_invalid_values(database, changes):
    engine, _, _ = database
    values = {
        "id": uuid4(),
        "name": "Тестовый зал",
        "hourly_price_minor": 100_000,
        "opens_at": time(9),
        "closes_at": time(23),
    }
    values.update(changes)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(Room).values(**values))


def test_health_and_templates(database):
    _, settings, _ = database
    from app.main import create_app

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
        assert response.headers["cache-control"] == "no-store"
        assert "Lumen Studio" in client.get("/").text
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_health_reports_unavailable_database(database):
    _, settings, _ = database
    from app.main import create_app

    settings = settings.model_copy(update={"postgres_host": "127.0.0.1", "postgres_port": 1})
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert settings.postgres_password.get_secret_value() not in response.text
