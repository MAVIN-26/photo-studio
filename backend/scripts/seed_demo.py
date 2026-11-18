import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import password_hasher
from app.bookings.models import EventLog, ScheduleEntry
from app.bookings.service import HOUR, STUDIO_ZONE, studio_now
from app.config import get_settings
from app.database import create_database_engine
from app.rooms.models import Room
from scripts.seed_rooms import DEMO_ROOMS, seed_rooms

DAYS = 7
CLIENTS = (
    ("client-1", "Анна · демо", "+12025550101"),
    ("client-2", "Илья · демо", "+12025550102"),
    ("client-3", "Мария · демо", "+12025550103"),
)
PRIMARY_STATUSES = ("pending_payment", "paid", "confirmed", "manual")


@dataclass
class SeedResult:
    rooms: int = 0
    bookings: int = 0
    blocks: int = 0
    skipped: int = 0
    credentials: dict[str, str] = field(default_factory=dict, repr=False)


def demo_id(key: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"lumenbook.demo.{key}")


def ensure_user(
    db: Session, key: str, name: str, role: str, now: datetime, result: SeedResult
) -> UUID:
    user_id = demo_id(key)
    email = f"lumenbook-demo-{key}@example.com"
    user = db.get(User, user_id)
    if user is None:
        password = secrets.token_urlsafe(18)
        inserted = db.scalar(
            insert(User)
            .values(
                id=user_id,
                name=name,
                email=email,
                role=role,
                password_hash=password_hasher.hash(password),
                consent_at=now if role == "client" else None,
            )
            .on_conflict_do_nothing()
            .returning(User.id)
        )
        if inserted is not None:
            result.credentials[email] = password
            return user_id
        user = db.get(User, user_id)
    if user is None or user.email != email or user.role != role:
        raise ValueError(f"Не удалось создать демо-аккаунт {email}: идентификатор уже занят.")
    return user_id


def find_interval(
    room: Room,
    day: date,
    now: datetime,
    occupied: list[tuple[datetime, datetime]],
    preferred_hour: int,
    duration: int,
) -> tuple[datetime, datetime] | None:
    hours = sorted(
        range(room.opens_at.hour, room.closes_at.hour - duration + 1),
        key=lambda hour: (abs(hour - preferred_hour), hour),
    )
    for hour in hours:
        start = datetime.combine(day, time(hour), STUDIO_ZONE)
        end = start + duration * HOUR
        if start > now and all(
            start >= other_end or end <= other_start for other_start, other_end in occupied
        ):
            return start, end
    return None


def add_event(
    db: Session,
    entry: ScheduleEntry,
    actor_id: UUID,
    event: str,
    at: datetime,
) -> None:
    db.add(
        EventLog(
            entry_id=entry.id,
            actor_id=actor_id,
            event_type=event,
            created_at=at,
            payload={},
        )
    )
    if entry.kind == "booking":
        db.add(
            EventLog(
                entry_id=entry.id,
                actor_id=actor_id,
                event_type="notification_simulated",
                created_at=at,
                payload={"trigger": event},
            )
        )


def add_entry(
    db: Session,
    *,
    entry_id: UUID,
    room: Room,
    scenario: str,
    interval: tuple[datetime, datetime],
    now: datetime,
    client: tuple[UUID, str, str],
    admin_id: UUID,
    result: SeedResult,
) -> None:
    start, end = interval
    created_at = now - timedelta(minutes=3)
    client_id, name, phone = client
    maintenance = scenario in ("cleaning", "repair")
    manual = scenario == "manual"
    actor_id = admin_id if maintenance or manual else client_id
    entry = ScheduleEntry(
        id=entry_id,
        room_id=room.id,
        starts_at=start,
        ends_at=end,
        kind="maintenance" if maintenance else "booking",
        status="confirmed" if maintenance or manual else scenario,
        source="maintenance" if maintenance else "phone" if manual else "website",
        created_by=actor_id,
        created_at=created_at,
        updated_at=now,
    )
    db.add(entry)
    if maintenance:
        entry.block_reason = scenario
        db.flush([entry])
        add_event(db, entry, admin_id, "block_created", created_at)
        result.blocks += 1
        return

    entry.user_id = None if manual else client_id
    entry.contact_name = name
    entry.contact_phone = phone
    entry.comment = "Демонстрационная запись."
    entry.hourly_price_minor = room.hourly_price_minor
    entry.total_price_minor = room.hourly_price_minor * ((end - start) // HOUR)
    if scenario in ("paid", "confirmed"):
        entry.paid_at = now - timedelta(minutes=2)
    db.flush([entry])
    add_event(db, entry, actor_id, "booking_created", created_at)
    if entry.paid_at is not None:
        add_event(db, entry, client_id, "booking_paid", entry.paid_at)
    if scenario == "confirmed":
        add_event(db, entry, admin_id, "booking_confirmed", now - timedelta(minutes=1))
    if scenario == "cancelled":
        add_event(db, entry, admin_id, "booking_cancelled", now - timedelta(minutes=1))
    result.bookings += 1


def seed_demo(engine: Engine, *, now: datetime | None = None) -> SeedResult:
    now = studio_now() if now is None else now.astimezone(STUDIO_ZONE)
    result = SeedResult(rooms=seed_rooms(engine))
    start_day = now.date()
    window_end = datetime.combine(start_day + timedelta(days=DAYS), time.min, STUDIO_ZONE)
    with Session(engine) as db, db.begin():
        admin_id = ensure_user(db, "admin", "Демо-администратор", "admin", now, result)
        clients = [
            (ensure_user(db, key, name, "client", now, result), name, phone)
            for key, name, phone in CLIENTS
        ]
        for room_index, (slug, *_) in enumerate(DEMO_ROOMS):
            room_id = uuid5(NAMESPACE_DNS, f"lumenbook.room.{slug}")
            room = db.scalars(select(Room).where(Room.id == room_id).with_for_update()).one()
            occupied = [
                (start, end)
                for start, end in db.execute(
                    select(ScheduleEntry.starts_at, ScheduleEntry.ends_at).where(
                        ScheduleEntry.room_id == room_id,
                        ScheduleEntry.status != "cancelled",
                        ScheduleEntry.starts_at < window_end,
                        ScheduleEntry.ends_at > now,
                    )
                )
            ]
            for offset in range(DAYS):
                day = start_day + timedelta(days=offset)
                rotation = day.toordinal() + room_index
                plan = (
                    ("primary", PRIMARY_STATUSES[rotation % len(PRIMARY_STATUSES)], 11, 2),
                    ("secondary", "cancelled" if rotation % 2 else "pending_payment", 15, 1),
                    ("block", "cleaning" if rotation % 2 else "repair", 19, 1),
                )
                for key, scenario, preferred_hour, duration in plan:
                    entry_id = demo_id(f"{slug}.{day}.{key}")
                    if db.get(ScheduleEntry, entry_id) is not None:
                        continue
                    interval = find_interval(room, day, now, occupied, preferred_hour, duration)
                    if interval is None:
                        result.skipped += 1
                        continue
                    client_index = rotation + 1 if key == "secondary" else rotation
                    add_entry(
                        db,
                        entry_id=entry_id,
                        room=room,
                        scenario=scenario,
                        interval=interval,
                        now=now,
                        client=clients[client_index % len(clients)],
                        admin_id=admin_id,
                        result=result,
                    )
                    if scenario != "cancelled":
                        occupied.append(interval)
    return result


def main() -> None:
    engine = create_database_engine(get_settings())
    try:
        result = seed_demo(engine)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except SQLAlchemyError:
        raise SystemExit("Не удалось записать демо-данные. Проверьте БД и миграции.") from None
    finally:
        engine.dispose()

    print(
        f"Добавлено: залов — {result.rooms}, аккаунтов — {len(result.credentials)}, "
        f"броней — {result.bookings}, блокировок — {result.blocks}."
    )
    if result.skipped:
        print(f"Пропущено из-за отсутствия подходящего интервала: {result.skipped}.")
    if result.credentials:
        print("Вход в новые демо-аккаунты (сохраните пароли):")
        for email, password in result.credentials.items():
            print(f"{email} — {password}")


if __name__ == "__main__":
    main()
