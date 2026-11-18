from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session
from test_bookings import booking_body, register

from app.auth.models import User
from app.bookings.models import EventLog, ScheduleEntry
from app.bookings.service import STUDIO_ZONE
from scripts.create_admin import create_admin

PASSWORD = "Demo-password-123"


def test_admin_schedule_permissions_and_filters(database):
    from app.main import create_app
    from scripts.seed_rooms import seed_rooms

    engine, settings, _ = database
    seed_rooms(engine)
    with Session(engine) as db:
        create_admin(db, "Администратор", "schedule-admin@example.ru", PASSWORD)
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.email == "schedule-admin@example.ru"))

    with TestClient(create_app(settings)) as client, TestClient(create_app(settings)) as admin:
        now = datetime.now(STUDIO_ZONE)
        day = now.date() + timedelta(days=2)
        headers = register(client, "schedule-client@example.ru")
        interval = {
            "starts_at": f"{day}T13:00:00+03:00",
            "ends_at": f"{day}T15:00:00+03:00",
        }
        body = booking_body(client, **interval, comment="Подготовить фон")
        response = client.post("/api/v1/bookings", headers=headers, json=body)
        assert response.status_code == 201, response.text
        booking = response.json()
        room_id = booking["room_id"]
        booking_id = booking["id"]
        schedule_url = "/api/v1/admin/schedule"
        detail_url = f"/api/v1/admin/bookings/{booking_id}"
        params = {"date_from": day.isoformat(), "date_to": day.isoformat()}
        assert client.get(schedule_url, params=params).status_code == 403
        assert client.get(detail_url).status_code == 403
        assert admin.get(schedule_url, params=params).status_code == 401
        assert admin.get(detail_url).status_code == 401

        token = admin.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = admin.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": token},
            json={"identifier": "schedule-admin@example.ru", "password": PASSWORD},
        )
        assert login.status_code == 200

        with engine.begin() as connection:
            block_id = connection.scalar(
                insert(ScheduleEntry)
                .values(
                    room_id=room_id,
                    kind="maintenance",
                    status="confirmed",
                    starts_at=datetime.combine(day, datetime.min.time(), STUDIO_ZONE).replace(
                        hour=15
                    ),
                    ends_at=datetime.combine(day, datetime.min.time(), STUDIO_ZONE).replace(
                        hour=16
                    ),
                    source="maintenance",
                    block_reason="cleaning",
                    created_by=admin_id,
                )
                .returning(ScheduleEntry.id)
            )
        response = admin.get(schedule_url, params=params | {"room_id": room_id})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        schedule = response.json()
        assert [room["id"] for room in schedule["rooms"]] == [room_id]
        assert [item["id"] for item in schedule["bookings"]] == [booking_id]
        assert schedule["blocks"][0]["id"] == str(block_id)
        assert schedule["blocks"][0]["status"] == "active"
        assert schedule["blocks"][0]["reason"] == "cleaning"
        detail = admin.get(detail_url).json()
        assert detail["contact_phone"] == "+79990000001"
        assert detail["comment"] == "Подготовить фон"
        assert admin.get(f"/api/v1/admin/bookings/{block_id}").status_code == 404
        assert admin.get(f"/api/v1/admin/bookings/{uuid4()}").status_code == 404

        page = admin.get("/admin", params={"date": day.isoformat()})
        assert page.status_code == 200
        assert f'data-booking-id="{booking_id}"' in page.text
        assert "grid-row: 5 / span 2" in page.text
        assert "Уборка" in page.text
        assert detail["contact_phone"] not in page.text

        day_after = (day + timedelta(days=1)).isoformat()
        assert (
            admin.get(schedule_url, params=dict.fromkeys(params, day_after)).json()["bookings"]
            == []
        )
        assert (
            admin.get(
                schedule_url, params=params | {"date_to": (day + timedelta(days=6)).isoformat()}
            ).status_code
            == 200
        )
        assert (
            admin.get(
                schedule_url, params=params | {"date_to": (day + timedelta(days=7)).isoformat()}
            ).status_code
            == 422
        )
        assert admin.get(schedule_url, params=params | {"date_from": day_after}).status_code == 422
        with engine.begin() as connection:
            connection.execute(
                update(ScheduleEntry)
                .where(ScheduleEntry.kind == "booking")
                .values(status="cancelled")
            )
        assert admin.get(schedule_url, params=params).json()["bookings"] == []
        assert admin.get(detail_url).json()["status"] == "cancelled"


def test_admin_booking_actions(database, monkeypatch):
    from app.bookings import service
    from app.main import create_app
    from scripts.seed_rooms import seed_rooms

    engine, settings, _ = database
    seed_rooms(engine)
    with Session(engine) as db:
        create_admin(db, "Администратор", "actions-admin@example.ru", PASSWORD)
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.email == "actions-admin@example.ru"))

    now = datetime(2026, 11, 18, 11, tzinfo=STUDIO_ZONE)
    monkeypatch.setattr(service, "studio_now", lambda: now)
    app = create_app(settings)
    with TestClient(app) as client, TestClient(app) as admin:
        client_headers = register(client, "actions-client@example.ru")
        token = admin.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = admin.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": token},
            json={"identifier": "actions-admin@example.ru", "password": PASSWORD},
        )
        assert login.status_code == 200
        admin_headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        day = now.date()

        def create(start, end):
            response = client.post(
                "/api/v1/bookings",
                headers=client_headers,
                json=booking_body(
                    client,
                    starts_at=f"{day}T{start}:00:00+03:00",
                    ends_at=f"{day}T{end}:00:00+03:00",
                ),
            )
            assert response.status_code == 201
            return response.json()

        booking = create(13, 15)
        create(18, 20)
        url = f"/api/v1/admin/bookings/{booking['id']}"
        client_url = f"/api/v1/bookings/{booking['id']}"
        assert (
            client.post(url + "/confirm", json={"version": 1}, headers=client_headers).status_code
            == 403
        )
        assert admin.post(url + "/confirm", json={"version": 1}).status_code == 403
        assert (
            admin.post(url + "/confirm", json={"version": 1}, headers=admin_headers).json()[
                "error"
            ]["code"]
            == "INVALID_BOOKING_STATE"
        )

        paid = client.post(client_url + "/pay", json={"version": 1}, headers=client_headers)
        assert paid.status_code == 200
        monkeypatch.setattr(service, "studio_now", lambda: now + timedelta(hours=4, minutes=40))
        stale = admin.post(url + "/confirm", json={"version": 1}, headers=admin_headers)
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        response = admin.post(url + "/confirm", json={"version": 2}, headers=admin_headers)
        assert response.status_code == 200
        confirmed = response.json()
        assert confirmed["status"] == "confirmed" and confirmed["confirmed_at"]
        assert set(confirmed["allowed_actions"]) == {"cancel", "reschedule"}
        assert admin.get(url).json()["confirmed_at"] == confirmed["confirmed_at"]
        assert client.get(client_url).json()["allowed_actions"] == []

        def move(version, start, end):
            return admin.post(
                url + "/reschedule",
                headers=admin_headers,
                json={
                    "version": version,
                    "starts_at": f"{day}T{start}:00:00+03:00",
                    "ends_at": f"{day}T{end}:00:00+03:00",
                },
            )

        assert move(3, 14, 16).json()["error"]["code"] == "INVALID_TIME_RANGE"
        assert move(3, 16, 17).json()["error"]["code"] == "DURATION_CHANGE_NOT_ALLOWED"
        assert move(3, 17, 19).json()["error"]["code"] == "SLOT_UNAVAILABLE"
        assert admin.get(url).json()["version"] == 3
        response = move(3, 16, 18)
        assert response.status_code == 200
        moved = response.json()
        assert moved["status"] == "confirmed"
        assert moved["total_price_minor"] == booking["total_price_minor"]
        assert moved["paid_at"] == confirmed["paid_at"]
        assert client.get(url + "/availability", params={"date": day}).status_code == 403
        data = admin.get(url + "/availability", params={"date": day}).json()
        assert data["slots"][7]["available"] and data["slots"][8]["available"]
        assert not data["slots"][9]["available"]

        response = admin.post(url + "/cancel", json={"version": 4}, headers=admin_headers)
        assert response.status_code == 200
        cancelled = response.json()
        assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"]
        assert cancelled["paid_at"] == confirmed["paid_at"] and cancelled["version"] == 5
        assert cancelled["allowed_actions"] == []
        schedule = admin.get("/api/v1/admin/schedule", params={"date_from": day, "date_to": day})
        assert booking["id"] not in {entry["id"] for entry in schedule.json()["bookings"]}
        assert create(16, 18)["id"] != booking["id"]

        with engine.connect() as connection:
            events = connection.scalars(
                select(EventLog.event_type).where(EventLog.actor_id == admin_id)
            ).all()
        assert sorted(events) == [
            "booking_cancelled",
            "booking_confirmed",
            "booking_rescheduled",
            "notification_simulated",
            "notification_simulated",
            "notification_simulated",
        ]
