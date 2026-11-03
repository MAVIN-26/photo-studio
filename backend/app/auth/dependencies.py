import secrets
from typing import Annotated, NoReturn
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request

from app.auth.models import AuthSession, User
from app.auth.service import COOKIE_NAME, find_session
from app.dependencies import Database


def fail(status: int, code: str, message: str) -> NoReturn:
    raise HTTPException(status, detail={"code": code, "message": message, "details": []})


def optional_user(request: Request, db: Database) -> User | None:
    session = find_session(db, request.cookies.get(COOKIE_NAME))
    return db.get(User, session.user_id) if session and session.user_id else None


def require_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        fail(401, "AUTHENTICATION_REQUIRED", "Войдите в аккаунт.")
    return user


CurrentUser = Annotated[User, Depends(require_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        fail(403, "ADMIN_ACCESS_REQUIRED", "Доступ разрешён только администратору.")
    return user


def require_client(user: CurrentUser) -> User:
    if user.role != "client":
        fail(403, "CLIENT_ACCESS_REQUIRED", "Доступ разрешён только клиенту.")
    return user


def require_csrf(request: Request, db: Database) -> AuthSession:
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        try:
            origin = urlsplit(source)
        except ValueError:
            fail(403, "CSRF_INVALID", "Обновите страницу и повторите действие.")
        if (origin.scheme, origin.netloc) != (request.url.scheme, request.url.netloc):
            fail(403, "CSRF_INVALID", "Обновите страницу и повторите действие.")
    session = find_session(db, request.cookies.get(COOKIE_NAME), lock=True)
    token = request.headers.get("x-csrf-token", "")
    if not session or not secrets.compare_digest(token.encode(), session.csrf_token.encode()):
        fail(403, "CSRF_INVALID", "Обновите страницу и повторите действие.")
    return session


CsrfSession = Annotated[AuthSession, Depends(require_csrf)]
