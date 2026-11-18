from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session
from test_bookings import booking_body, register

from app.auth.models import User
from app.bookings.models import ScheduleEntry
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
