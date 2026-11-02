import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, User
from app.auth.schemas import normalize_email, normalize_phone

COOKIE_NAME = "lumenbook_session"
password_hasher = PasswordHash.recommended()
# Проверка фиктивного хеша выравнивает стоимость входа для неизвестного пользователя.
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def find_session(db: Session, token: str | None, *, lock: bool = False) -> AuthSession | None:
    if not token or len(token) > 128:
        return None
    query = select(AuthSession).where(
        AuthSession.token_hash == token_hash(token), AuthSession.expires_at > datetime.now(UTC)
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def new_session(db: Session, ttl_hours: int, user: User | None = None) -> tuple[AuthSession, str]:
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=token_hash(token),
        user_id=user.id if user else None,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    db.add(session)
    db.flush()
    return session, token


def authenticate(db: Session, identifier: str, password: str) -> User | None:
    try:
        if "@" in identifier:
            query = select(User).where(User.email == normalize_email(identifier))
        else:
            query = select(User).where(User.phone == normalize_phone(identifier))
        user = db.scalar(query)
    except ValueError:
        user = None
    valid = password_hasher.verify(password, user.password_hash if user else DUMMY_HASH)
    return user if user and valid else None
