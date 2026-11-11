from datetime import datetime

from app.bookings.service import STUDIO_ZONE


def studio_format(value: datetime, pattern: str) -> str:
    return value.astimezone(STUDIO_ZONE).strftime(pattern)


def format_price_minor(value: int) -> str:
    rubles, kopecks = divmod(value, 100)
    price = f"{rubles:,}".replace(",", " ")
    return f"{price},{kopecks:02d}" if kopecks else price
