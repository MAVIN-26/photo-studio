from datetime import date, datetime, time

from app.admin.schemas import AdminSchedule
from app.bookings import service

FIRST_HOUR = 9
LAST_HOUR = 23
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def short_date(day: date) -> str:
    return f"{WEEKDAYS_SHORT[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def date_label(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]} {day.year}"


def schedule_columns(schedule: AdminSchedule) -> list[dict]:
    entries_by_room = {room.id: [] for room in schedule.rooms}
    for entry in [*schedule.bookings, *schedule.blocks]:
        entries_by_room[entry.room_id].append(entry)
    columns = []
    for room in schedule.rooms:
        entries = entries_by_room[room.id]
        blocks = []
        occupied = set()
        for entry in entries:
            start = entry.starts_at.astimezone(service.STUDIO_ZONE)
            end = entry.ends_at.astimezone(service.STUDIO_ZONE)
            occupied.update(range(start.hour, end.hour))
            blocks.append(
                {
                    "entry": entry,
                    "row": start.hour - FIRST_HOUR + 1,
                    "span": end.hour - start.hour,
                    "time": f"{start:%H:%M}–{end:%H:%M}",
                }
            )
        columns.append(
            {
                "room": room,
                "entries": blocks,
                "count": sum(entry.status != "active" for entry in entries),
                "free_hours": {
                    hour
                    for hour in range(room.opens_at.hour, room.closes_at.hour)
                    if hour not in occupied
                    and datetime.combine(schedule.date_from, time(hour), service.STUDIO_ZONE)
                    > schedule.server_now
                },
            }
        )
    return columns
