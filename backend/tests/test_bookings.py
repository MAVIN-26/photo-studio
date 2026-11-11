from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.bookings import service
from app.bookings.models import EventLog, ScheduleEntry
from app.rooms.models import Room
from scripts.seed_rooms import seed_rooms

NOW = datetime(2026, 11, 11, 12, 30, tzinfo=service.STUDIO_ZONE)
DAY = NOW.date()


@pytest.fixture
def app(database, monkeypatch):
    from app.main import create_app

    seed_rooms(database[0])
    monkeypatch.setattr(service, "studio_now", lambda: NOW)
    return create_app(database[1])


def register(client, email):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        headers={"X-CSRF-Token": token},
        json={"name": "Клиент", "email": email, "password": "Demo-password-123", "consent": True},
    )
    assert response.status_code == 201
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def booking_body(client, **changes):
    room = client.get("/api/v1/rooms").json()["items"][0]
    return {
        "room_id": room["id"],
        "room_version": room["version"],
        "starts_at": f"{DAY}T13:00:00+03:00",
        "ends_at": f"{DAY}T15:00:00+03:00",
        "contact_name": "  Клиент  ",
        "contact_phone": "+7 (999) 000-00-01",
    } | changes


def test_creation_occupies_time_and_preserves_owner_price_and_audit(app, database):
    with TestClient(app) as client, TestClient(app) as other:
        body = booking_body(client)
        url = f"/api/v1/rooms/{body['room_id']}/availability?date={DAY}"
        before = other.get(url).json()
        assert [slot["available"] for slot in before["slots"][:5]] == [False] * 4 + [True]
        headers = register(client, "booking@example.ru")
        assert client.post("/api/v1/bookings", json=body).status_code == 403
        result = client.post("/api/v1/bookings", json=body, headers=headers)
        assert result.status_code == 201, result.text
        booking = result.json()
        assert booking["status"] == "pending_payment"
        assert booking["hourly_price_minor"] == 200_000
        assert booking["total_price_minor"] == 400_000
        assert booking["contact_phone"] == "+79990000001"
        assert booking["contact_name"] == "Клиент"
        detail = result.headers["Location"]
        assert client.get(detail).status_code == 200
        assert client.get(f"/my/bookings/{booking['id']}").status_code == 200

        after = other.get(url).json()
        assert [slot["available"] for slot in after["slots"][4:7]] == [False, False, True]
        assert all(set(slot) == {"starts_at", "ends_at", "available"} for slot in after["slots"])
        assert other.get(detail).status_code == 401
        register(other, "other@example.ru")
        assert other.get(detail).status_code == 404
        assert other.get("/api/v1/bookings").json()["total"] == 0
        with database[0].begin() as connection:
            connection.execute(update(Room).values(hourly_price_minor=250_000, version=2))
            events = connection.execute(select(EventLog.event_type)).scalars().all()
        assert sorted(events) == ["booking_created", "notification_simulated"]
        assert client.get(detail).json()["total_price_minor"] == 400_000
        assert client.get("/api/v1/bookings?scope=upcoming").json()["total"] == 1
        assert client.get("/api/v1/bookings?scope=past").json()["total"] == 0


def test_concurrent_clients_and_adjacent_slots(app, database):
    with TestClient(app) as first, TestClient(app) as second:
        headers = [register(first, "first@example.ru"), register(second, "second@example.ru")]
        body = booking_body(first)
        with ThreadPoolExecutor(2) as executor:
            results = list(
                executor.map(
                    lambda pair: pair[0].post("/api/v1/bookings", json=body, headers=pair[1]),
                    zip((first, second), headers, strict=True),
                )
            )
        assert sorted(result.status_code for result in results) == [201, 409]
        conflict = next(result for result in results if result.status_code == 409)
        assert conflict.json()["error"]["code"] == "SLOT_UNAVAILABLE"
        adjacent = body | {"starts_at": f"{DAY}T15:00:00+03:00", "ends_at": f"{DAY}T16:00:00+03:00"}
        assert second.post("/api/v1/bookings", json=adjacent, headers=headers[1]).status_code == 201
        with database[0].connect() as connection:
            assert len(connection.execute(select(ScheduleEntry.id)).all()) == 2
            assert len(connection.execute(select(EventLog.id)).all()) == 4


def test_database_rejects_overlap_with_maintenance_and_releases_cancelled(app, database):
    with TestClient(app) as client:
        headers = register(client, "schedule@example.ru")
        body = booking_body(client)
        result = client.post("/api/v1/bookings", json=body, headers=headers)
        assert result.status_code == 201
        entry = result.json()
        block = {
            "room_id": UUID(entry["room_id"]),
            "created_by": UUID(entry["user_id"]),
            "kind": "maintenance",
            "status": "confirmed",
            "source": "maintenance",
            "block_reason": "cleaning",
            "starts_at": datetime.fromisoformat(body["starts_at"]),
            "ends_at": datetime.fromisoformat(body["ends_at"]),
        }
        with pytest.raises(IntegrityError) as failure, database[0].begin() as connection:
            connection.execute(insert(ScheduleEntry).values(**block))
        assert failure.value.orig.diag.constraint_name == "ex_schedule_entries_room_interval"
        with database[0].begin() as connection:
            connection.execute(update(ScheduleEntry).values(status="cancelled"))
            connection.execute(insert(ScheduleEntry).values(**block))
        result = client.post("/api/v1/bookings", json=body, headers=headers)
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "SLOT_UNAVAILABLE"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"room_version": 2}, "ROOM_SETTINGS_CHANGED"),
        ({"starts_at": f"{DAY}T12:00:00+03:00"}, "INVALID_TIME_RANGE"),
        ({"starts_at": f"{DAY}T13:30:00+03:00"}, "INVALID_TIME_RANGE"),
        ({"starts_at": f"{DAY}T13:00:00"}, "VALIDATION_ERROR"),
        ({"ends_at": f"{DAY}T15:00:00.000001+03:00"}, "INVALID_TIME_RANGE"),
        ({"ends_at": f"{DAY}T23:30:00+03:00"}, "INVALID_TIME_RANGE"),
        ({"ends_at": f"{DAY + timedelta(days=1)}T10:00:00+03:00"}, "INVALID_TIME_RANGE"),
        ({"total_price_minor": 1}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_booking_changes_are_rejected(app, changes, code):
    with TestClient(app) as client:
        headers = register(client, "invalid@example.ru")
        result = client.post(
            "/api/v1/bookings", json=booking_body(client, **changes), headers=headers
        )
        assert result.status_code in (409, 422)
        assert result.json()["error"]["code"] == code
        assert client.get("/api/v1/bookings").json()["total"] == 0


def test_availability_includes_day_thirty_but_not_day_thirty_one(app):
    with TestClient(app) as client:
        room = booking_body(client)["room_id"]
        url = f"/api/v1/rooms/{room}/availability"
        for delta, status in [(-1, 422), (0, 200), (30, 200), (31, 422)]:
            response = client.get(url, params={"date": str(DAY + timedelta(days=delta))})
            assert response.status_code == status
            if status == 422:
                assert response.json()["error"]["code"] == "DATE_OUT_OF_RANGE"
