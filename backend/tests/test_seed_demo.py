from datetime import datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import password_hasher
from app.bookings.models import EventLog, ScheduleEntry
from app.bookings.service import STUDIO_ZONE
from app.rooms.models import Room
from scripts.seed_demo import DAYS, demo_id, seed_demo
from scripts.seed_rooms import seed_rooms


def test_demo_seed_preserves_existing_entries_and_extends_window(database):
    engine, _, _ = database
    now = datetime(2026, 11, 18, 10, tzinfo=STUDIO_ZONE)
    other_id = uuid4()
    existing_id = uuid4()
    seed_rooms(engine)
    with engine.begin() as connection:
        room_id = connection.scalar(select(Room.id).where(Room.name == "Лофт"))
        connection.execute(
            update(Room)
            .where(Room.id == room_id)
            .values(
                hourly_price_minor=300_000,
                opens_at=time(10),
                closes_at=time(21),
                version=2,
            )
        )
        connection.execute(
            insert(User).values(
                id=other_id,
                email="existing-admin@example.com",
                name="Администратор",
                password_hash="unused-in-test",
                role="admin",
            )
        )
        connection.execute(
            insert(ScheduleEntry).values(
                id=existing_id,
                room_id=room_id,
                starts_at=now.replace(hour=11),
                ends_at=now.replace(hour=13),
                kind="maintenance",
                status="confirmed",
                source="maintenance",
                created_by=other_id,
                block_reason="repair",
            )
        )

    first = seed_demo(engine, now=now)
    assert len(first.credentials) == 4
    assert first.rooms == first.skipped == 0
    assert first.bookings == 4 * DAYS * 2
    assert first.blocks == 4 * DAYS

    with Session(engine) as db:
        client = db.get(User, demo_id("client-1"))
        assert password_hasher.verify(first.credentials[client.email], client.password_hash)
        original = db.get(ScheduleEntry, existing_id)
        assert original.starts_at == now.replace(hour=11) and original.status == "confirmed"
        rows = list(db.scalars(select(ScheduleEntry).where(ScheduleEntry.id != existing_id)))
        assert {row.starts_at.astimezone(STUDIO_ZONE).date() for row in rows} == {
            now.date() + timedelta(days=offset) for offset in range(DAYS)
        }
        assert all(row.starts_at > now for row in rows)
        assert {row.status for row in rows if row.kind == "booking"} == {
            "pending_payment",
            "paid",
            "confirmed",
            "cancelled",
        }
        assert {row.block_reason for row in rows if row.kind == "maintenance"} == {
            "cleaning",
            "repair",
        }
        assert any(row.source == "phone" and row.user_id is None for row in rows)
        loft = [row for row in rows if row.room_id == room_id]
        assert all(row.ends_at.astimezone(STUDIO_ZONE).time() <= time(21) for row in loft)
        assert all(row.hourly_price_minor == 300_000 for row in loft if row.kind == "booking")
        paid = next(row for row in rows if row.status == "paid")
        event = db.scalar(
            select(EventLog).where(
                EventLog.entry_id == paid.id,
                EventLog.payload["trigger"].as_string() == "booking_paid",
            )
        )
        assert event is not None
        paid.status = "cancelled"
        changed_id = paid.id
        db.commit()

    second = seed_demo(engine, now=now)
    assert (second.rooms, second.bookings, second.blocks, second.credentials) == (0, 0, 0, {})
    third = seed_demo(engine, now=now + timedelta(days=1))
    assert (third.bookings, third.blocks, third.credentials) == (8, 4, {})
    with Session(engine) as db:
        assert db.get(ScheduleEntry, changed_id).status == "cancelled"
        assert db.get(Room, room_id).hourly_price_minor == 300_000
        assert db.get(Room, room_id).version == 2
