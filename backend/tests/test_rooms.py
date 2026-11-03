from datetime import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.rooms.models import Room
from app.web.formatters import format_price_minor
from scripts.seed_rooms import seed_rooms


@pytest.fixture
def catalog(database):
    from app.main import create_app

    seed_rooms(database[0])
    with TestClient(create_app(database[1])) as client:
        yield client


def test_public_catalog_and_detail_follow_contract(catalog):
    response = catalog.get("/api/v1/rooms")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    items = response.json()["items"]
    assert [room["name"] for room in items] == ["Циклорама", "Лофт", "Неон", "Сканди"]
    assert {room["hourly_price_minor"] for room in items} == {200_000, 250_000, 180_000, 220_000}
    for room in items:
        assert set(room) == {
            "id",
            "name",
            "description",
            "image_url",
            "hourly_price_minor",
            "currency",
            "opens_at",
            "closes_at",
            "timezone",
            "version",
        }
        assert room["currency"] == "RUB"
        assert room["timezone"] == "Europe/Moscow"
        assert (room["opens_at"], room["closes_at"]) == ("09:00", "23:00")
        assert room["version"] == 1
        assert room["description"]
        assert catalog.get(room["image_url"]).status_code == 200
        detail = catalog.get(f"/api/v1/rooms/{room['id']}")
        assert detail.status_code == 200
        assert detail.json() == room
        page = catalog.get(f"/rooms/{room['id']}")
        assert page.status_code == 200
        assert room["description"] in page.text
        assert f'<h1 id="room-title">{room["name"]}</h1>' in page.text
    assert catalog.get("/api/v1/auth/me").status_code == 401


def test_catalog_and_pages_reflect_current_database_values(catalog, database):
    with database[0].begin() as connection:
        room_id = connection.scalar(select(Room.id).where(Room.name == "Лофт"))
        connection.execute(
            update(Room)
            .where(Room.id == room_id)
            .values(
                hourly_price_minor=310_025,
                opens_at=time(10),
                closes_at=time(22),
                version=2,
                description='Тестовое описание <script>alert("xss")</script>',
                image_url=None,
            )
        )
    api = catalog.get(f"/api/v1/rooms/{room_id}").json()
    assert (api["hourly_price_minor"], api["opens_at"], api["version"]) == (310_025, "10:00", 2)
    assert api["image_url"] is None
    for path in ("/", f"/rooms/{room_id}"):
        response = catalog.get(path)
        assert response.status_code == 200
        assert "3 100,25 ₽" in response.text
        assert "10:00–22:00" in response.text
        assert "Изображение зала пока не добавлено" in response.text
        assert '<script>alert("xss")</script>' not in response.text
        assert "&lt;script&gt;" in response.text


def test_missing_room_and_invalid_identifiers(catalog):
    response = catalog.get(f"/api/v1/rooms/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "ROOM_NOT_FOUND", "message": "Зал не найден.", "details": []}
    }
    invalid = catalog.get("/api/v1/rooms/invalid")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    for identifier in (str(uuid4()), "invalid"):
        page = catalog.get(f"/rooms/{identifier}")
        assert page.status_code == 404
        assert page.headers["content-type"].startswith("text/html")
        assert "Зал не найден" in page.text


def test_empty_catalog_is_not_an_error(database):
    from app.main import create_app

    with TestClient(create_app(database[1])) as client:
        assert client.get("/api/v1/rooms").json() == {"items": []}
        page = client.get("/")
        assert page.status_code == 200
        assert "Залы пока не добавлены" in page.text


def test_seed_fills_missing_content_and_preserves_edits(database):
    engine = database[0]
    seed_rooms(engine)
    with engine.begin() as connection:
        connection.execute(
            update(Room)
            .where(Room.name == "Лофт")
            .values(
                description="",
                image_url=None,
                hourly_price_minor=320_000,
                opens_at=time(10),
                closes_at=time(22),
                version=3,
            )
        )
        connection.execute(
            update(Room)
            .where(Room.name == "Неон")
            .values(
                description="Авторское описание",
                image_url="/static/custom.svg",
            )
        )
    assert seed_rooms(engine) == 0
    with engine.connect() as connection:
        loft = connection.execute(select(Room).where(Room.name == "Лофт")).one()
        assert loft.description.startswith("Кирпичные стены")
        assert loft.image_url == "/static/rooms/loft.svg"
        assert (loft.hourly_price_minor, loft.opens_at, loft.closes_at, loft.version) == (
            320_000,
            time(10),
            time(22),
            3,
        )
        neon = connection.execute(select(Room).where(Room.name == "Неон")).one()
        assert (neon.description, neon.image_url) == ("Авторское описание", "/static/custom.svg")


@pytest.mark.parametrize(
    "minor,expected", [(200_000, "2 000"), (1, "0,01"), (110, "1,10"), (310_025, "3 100,25")]
)
def test_price_preserves_kopecks(minor, expected):
    assert format_price_minor(minor) == expected
