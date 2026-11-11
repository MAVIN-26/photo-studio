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


def future_booking(client, headers, *, start=13, end=15):
    day = DAY + timedelta(days=2)
    body = booking_body(
        client, starts_at=f"{day}T{start:02}:00:00+03:00", ends_at=f"{day}T{end:02}:00:00+03:00"
    )
    response = client.post("/api/v1/bookings", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_concurrent_pay_only_records_one_payment(app, database):
    with TestClient(app) as client, TestClient(app) as other:
        headers = register(client, "pay@example.ru")
        entry = future_booking(client, headers)
        url = f"/api/v1/bookings/{entry['id']}/pay"
        assert set(entry["allowed_actions"]) == {"pay", "cancel", "reschedule"}
        assert client.post(url, json={"version": 1}).status_code == 403
        # Две сессии одного клиента проверяют блокировку самой брони.
        csrf = other.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = other.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": csrf},
            json={"identifier": "pay@example.ru", "password": "Demo-password-123"},
        )
        assert login.status_code == 200
        other_headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        with ThreadPoolExecutor(2) as executor:
            first = executor.submit(client.post, url, json={"version": 1}, headers=headers)
            second = executor.submit(other.post, url, json={"version": 1}, headers=other_headers)
            results = [first.result(), second.result()]
        assert sorted(response.status_code for response in results) == [200, 409]
        paid = next(response.json() for response in results if response.status_code == 200)
        stale = next(response.json() for response in results if response.status_code == 409)
        assert stale["error"]["code"] == "VERSION_CONFLICT"
        assert paid["status"] == "paid" and paid["paid_at"] and paid["version"] == 2
        assert set(paid["allowed_actions"]) == {"cancel", "reschedule"}
        repeat = client.post(url, json={"version": 2}, headers=headers)
        assert repeat.status_code == 409
        assert repeat.json()["error"]["code"] == "INVALID_BOOKING_STATE"
        with database[0].connect() as connection:
            events = connection.scalars(select(EventLog.event_type)).all()
        assert events.count("booking_paid") == 1
        assert events.count("notification_simulated") == 2


def test_cancel_paid_booking_at_deadline_and_release_slot(app, monkeypatch):
    with TestClient(app) as client:
        headers = register(client, "cancel@example.ru")
        entry = future_booking(client, headers)
        url = f"/api/v1/bookings/{entry['id']}"
        paid = client.post(url + "/pay", json={"version": 1}, headers=headers).json()
        starts_at = datetime.fromisoformat(entry["starts_at"])
        cutoff = (starts_at - timedelta(hours=24)).astimezone(service.STUDIO_ZONE)
        monkeypatch.setattr(service, "studio_now", lambda: cutoff + timedelta(microseconds=1))
        assert client.get(url).json()["allowed_actions"] == []
        rejected = client.post(url + "/cancel", json={"version": 2}, headers=headers)
        assert rejected.json()["error"]["code"] == "CANCELLATION_DEADLINE_PASSED"

        monkeypatch.setattr(service, "studio_now", lambda: cutoff)
        response = client.post(url + "/cancel", json={"version": 2}, headers=headers)
        assert response.status_code == 200
        cancelled = response.json()
        assert cancelled["status"] == "cancelled" and cancelled["version"] == 3
        assert datetime.fromisoformat(cancelled["paid_at"]) == datetime.fromisoformat(
            paid["paid_at"]
        )
        assert cancelled["allowed_actions"] == []
        replacement = future_booking(client, headers)
        assert replacement["id"] != entry["id"]


def test_reschedule_preserves_terms_and_rolls_back_conflict(app, database, monkeypatch):
    with TestClient(app) as client, TestClient(app) as other:
        headers = register(client, "move@example.ru")
        other_headers = register(other, "neighbor@example.ru")
        entry = future_booking(client, headers)
        neighbor = future_booking(other, other_headers, start=17, end=19)
        url = f"/api/v1/bookings/{entry['id']}"
        paid = client.post(url + "/pay", json={"version": 1}, headers=headers).json()
        day = DAY + timedelta(days=2)
        public_url = f"/api/v1/rooms/{entry['room_id']}/availability?date={day}"
        private_url = url + f"/availability?date={day}"
        assert not client.get(public_url).json()["slots"][4]["available"]
        assert client.get(private_url).json()["slots"][4]["available"]
        assert other.get(private_url).status_code == 404
        assert (
            other.post(url + "/cancel", json={"version": 2}, headers=other_headers).status_code
            == 404
        )

        with database[0].begin() as connection:
            connection.execute(update(Room).values(hourly_price_minor=350_000, version=2))

        def move(version, start, end):
            return client.post(
                url + "/reschedule",
                headers=headers,
                json={
                    "version": version,
                    "starts_at": f"{day}T{start:02}:00:00+03:00",
                    "ends_at": f"{day}T{end:02}:00:00+03:00",
                },
            )

        cutoff = datetime.combine(day, datetime.min.time(), service.STUDIO_ZONE).replace(hour=13)
        cutoff -= timedelta(hours=24)
        monkeypatch.setattr(service, "studio_now", lambda: cutoff + timedelta(microseconds=1))
        assert move(2, 14, 16).json()["error"]["code"] == "RESCHEDULE_DEADLINE_PASSED"
        monkeypatch.setattr(service, "studio_now", lambda: cutoff)
        assert move(2, 14, 15).json()["error"]["code"] == "DURATION_CHANGE_NOT_ALLOWED"
        shifted = move(2, 14, 16)
        assert shifted.status_code == 200, shifted.text
        moved = shifted.json()
        assert moved["id"] == entry["id"] and moved["version"] == 3
        assert moved["status"] == "paid"
        assert datetime.fromisoformat(moved["paid_at"]) == datetime.fromisoformat(paid["paid_at"])
        assert moved["total_price_minor"] == entry["total_price_minor"]
        assert moved["hourly_price_minor"] == entry["hourly_price_minor"]

        conflict = move(3, 16, 18)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "SLOT_UNAVAILABLE"
        current = client.get(url).json()
        assert datetime.fromisoformat(current["starts_at"]) == datetime.fromisoformat(
            moved["starts_at"]
        )
        assert datetime.fromisoformat(current["ends_at"]) == datetime.fromisoformat(
            moved["ends_at"]
        )
        assert current["version"] == 3
        assert other.get(f"/api/v1/bookings/{neighbor['id']}").json()["version"] == 1
        with database[0].connect() as connection:
            events = connection.scalars(select(EventLog.event_type)).all()
        assert events.count("booking_rescheduled") == 1
