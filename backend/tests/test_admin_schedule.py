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


def test_manual_booking_permissions_and_shared_calendar(database, monkeypatch):
    from app.bookings import service
    from app.main import create_app
    from scripts.seed_rooms import seed_rooms

    engine, settings, _ = database
    seed_rooms(engine)
    email = "manual-admin@example.ru"
    with Session(engine) as db:
        create_admin(db, "Администратор", email, PASSWORD)
        db.commit()
        actor_id = db.scalar(select(User.id).where(User.email == email))

    now = datetime(2026, 11, 18, 11, tzinfo=STUDIO_ZONE)
    monkeypatch.setattr(service, "studio_now", lambda: now)
    app = create_app(settings)
    with TestClient(app) as client, TestClient(app) as admin:
        client_headers = register(client, "manual-client@example.ru")
        token = admin.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = admin.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": token},
            json={"identifier": email, "password": PASSWORD},
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        day = now.date()
        body = booking_body(
            client,
            starts_at=f"{day}T13:00:00+03:00",
            ends_at=f"{day}T15:00:00+03:00",
            comment="Понадобится фон",
        )
        manual = body | {"source": "vk"}
        url = "/api/v1/admin/bookings"
        assert client.post(url, headers=client_headers, json=manual).status_code == 403
        assert admin.post(url, json=manual).status_code == 403
        assert (
            admin.post(url, headers=headers, json=manual | {"source": "website"}).status_code == 422
        )
        assert (
            admin.post(url, headers=headers, json=manual | {"total_price_minor": 1}).status_code
            == 422
        )
        stale = admin.post(url, headers=headers, json=manual | {"room_version": 2})
        assert stale.json()["error"]["code"] == "ROOM_SETTINGS_CHANGED"

        response = admin.post(url, headers=headers, json=manual)
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["status"] == "confirmed"
        assert (
            created["source"] == "vk" and created["user_id"] is None and created["paid_at"] is None
        )
        assert created["total_price_minor"] == created["hourly_price_minor"] * 2
        assert admin.get(response.headers["Location"]).json()["id"] == created["id"]
        assert client.get(f"/api/v1/bookings/{created['id']}").status_code == 404
        availability_url = f"/api/v1/rooms/{body['room_id']}/availability?date={day}"
        slots = client.get(availability_url).json()["slots"]
        assert all(not slot["available"] for slot in slots[4:6])
        conflict = client.post("/api/v1/bookings", headers=client_headers, json=body)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "SLOT_UNAVAILABLE"
        adjacent = body | {"starts_at": f"{day}T15:00:00+03:00", "ends_at": f"{day}T16:00:00+03:00"}
        assert (
            client.post("/api/v1/bookings", headers=client_headers, json=adjacent).status_code
            == 201
        )
        conflict = admin.post(url, headers=headers, json=adjacent | {"source": "phone"})
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "SLOT_UNAVAILABLE"
        page = admin.get("/admin", params={"date": day}).text
        assert "Новая бронь: Циклорама, 13:00" not in page
        assert "Новая бронь: Циклорама, 16:00" in page

        with engine.connect() as connection:
            entry = connection.execute(
                select(ScheduleEntry.created_by).where(ScheduleEntry.id == created["id"])
            ).scalar_one()
            events = connection.scalars(
                select(EventLog.event_type).where(EventLog.entry_id == created["id"])
            ).all()
        assert entry == actor_id
        assert sorted(events) == ["booking_created", "notification_simulated"]


def test_room_settings_preserve_bookings_and_reject_conflicts(database, monkeypatch):
    from app.bookings import service
    from app.main import create_app
    from scripts.seed_rooms import seed_rooms

    engine, settings, _ = database
    seed_rooms(engine)
    email = "settings-admin@example.ru"
    with Session(engine) as db:
        create_admin(db, "Администратор", email, PASSWORD)
        db.commit()
        actor_id = db.scalar(select(User.id).where(User.email == email))

    now = datetime(2026, 11, 18, 11, tzinfo=STUDIO_ZONE)
    monkeypatch.setattr(service, "studio_now", lambda: now)
    app = create_app(settings)
    with TestClient(app) as client, TestClient(app) as admin:
        assert admin.get("/admin/rooms", follow_redirects=False).status_code == 303
        client_headers = register(client, "settings-client@example.ru")
        assert client.get("/admin/rooms").status_code == 403
        token = admin.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = admin.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": token},
            json={"identifier": email, "password": PASSWORD},
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        rooms = client.get("/api/v1/rooms").json()["items"]
        first, second = rooms[:2]
        assert "Настройки залов" in admin.get("/admin/rooms").text
        url = f"/api/v1/admin/rooms/{first['id']}"
        price_only = {"version": 1, "hourly_price_minor": 230_025}
        assert client.patch(url, json=price_only, headers=client_headers).status_code == 403
        assert admin.patch(url, json=price_only).status_code == 403
        for invalid in (
            {},
            {"opens_at": None},
            {"opens_at": "08:00"},
            {"closes_at": "23:30"},
            {"hourly_price_minor": 0},
            {"hourly_price_minor": 2_147_483_648},
            {"hourly_price_minor": 100.0},
            {"closes_at": "09:00"},
            {"description": "новое"},
        ):
            assert (
                admin.patch(url, json={"version": 1, **invalid}, headers=headers).status_code == 422
            )

        day = now.date()
        body = booking_body(
            client, starts_at=f"{day}T13:00:00+03:00", ends_at=f"{day}T15:00:00+03:00"
        )
        created = client.post("/api/v1/bookings", json=body, headers=client_headers)
        assert created.status_code == 201
        booking = created.json()
        with engine.begin() as connection:
            connection.execute(
                insert(ScheduleEntry).values(
                    room_id=second["id"],
                    kind="maintenance",
                    status="confirmed",
                    starts_at=now.replace(hour=20),
                    ends_at=now.replace(hour=21),
                    source="maintenance",
                    block_reason="cleaning",
                    created_by=actor_id,
                )
            )

        for room, field in [(first, {"closes_at": "14:00"}), (second, {"closes_at": "20:00"})]:
            room_url = f"/api/v1/admin/rooms/{room['id']}"
            conflict = admin.patch(room_url, json=price_only | field, headers=headers)
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "ROOM_SCHEDULE_CONFLICT"
            assert client.get(f"/api/v1/rooms/{room['id']}").json() == room

        updated = admin.patch(url, json=price_only | {"closes_at": "15:00"}, headers=headers)
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 2 and updated.json()["closes_at"] == "15:00"
        assert client.get(f"/api/v1/rooms/{first['id']}").json() == updated.json()
        assert (
            client.get(f"/api/v1/bookings/{booking['id']}").json()["total_price_minor"]
            == (booking["total_price_minor"])
        )
        stale = admin.patch(url, json=price_only, headers=headers)
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        old_quote = client.post("/api/v1/bookings", json=body, headers=client_headers)
        assert old_quote.json()["error"]["code"] == "ROOM_SETTINGS_CHANGED"
        renamed_price = admin.patch(url, json=price_only | {"version": 2}, headers=headers)
        assert renamed_price.json()["version"] == 2

        monkeypatch.setattr(service, "studio_now", lambda: now.replace(hour=16))
        after_booking = admin.patch(url, json={"version": 2, "closes_at": "14:00"}, headers=headers)
        assert after_booking.status_code == 200

        with engine.connect() as connection:
            events = (
                connection.execute(
                    select(EventLog.payload).where(
                        EventLog.actor_id == actor_id,
                        EventLog.event_type == "room_settings_changed",
                    )
                )
                .scalars()
                .all()
            )
        assert len(events) == 2
        price_change = next(event for event in events if "hourly_price_minor" in event["after"])
        assert price_change["before"]["hourly_price_minor"] == first["hourly_price_minor"]
        assert price_change["after"]["hourly_price_minor"] == 230_025
