from datetime import datetime

from app.bookings.service import STUDIO_ZONE
from app.web.schedule import short_date


def studio_format(value: datetime, pattern: str) -> str:
    return value.astimezone(STUDIO_ZONE).strftime(pattern)


def studio_day(value: datetime) -> str:
    return short_date(value.astimezone(STUDIO_ZONE).date())


def duration_label(hours: int) -> str:
    if 11 <= hours % 100 <= 14:
        unit = "часов"
    elif hours % 10 == 1:
        unit = "час"
    elif 2 <= hours % 10 <= 4:
        unit = "часа"
    else:
        unit = "часов"
    return f"{hours} {unit}"


def format_price_minor(value: int) -> str:
    rubles, kopecks = divmod(value, 100)
    price = f"{rubles:,}".replace(",", " ")
    return f"{price},{kopecks:02d}" if kopecks else price
