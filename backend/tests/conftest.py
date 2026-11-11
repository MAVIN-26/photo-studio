import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.auth.models import AuthSession, User
from app.bookings.models import EventLog, ScheduleEntry
from app.config import Settings
from app.rooms.models import Room


@pytest.fixture
def database(monkeypatch):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Для интеграционных проверок нужен TEST_DATABASE_URL")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or url.database != "lumenbook_test":
        pytest.fail("Проверки разрешены только в PostgreSQL с БД lumenbook_test")
    settings = Settings(
        postgres_db=url.database,
        postgres_user=url.username,
        postgres_password=url.password,
        postgres_host=url.host,
        postgres_port=url.port or 5432,
    )
    for key in ("db", "user", "host", "port"):
        monkeypatch.setenv(f"POSTGRES_{key.upper()}", str(getattr(settings, f"postgres_{key}")))
    monkeypatch.setenv("POSTGRES_PASSWORD", settings.postgres_password.get_secret_value())
    from app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(EventLog.__table__.delete())
            connection.execute(ScheduleEntry.__table__.delete())
            connection.execute(AuthSession.__table__.delete())
            connection.execute(User.__table__.delete())
            connection.execute(Room.__table__.delete())
        yield engine, settings, config
    finally:
        engine.dispose()
        get_settings.cache_clear()
