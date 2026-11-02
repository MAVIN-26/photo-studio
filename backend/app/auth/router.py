from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import CsrfSession, CurrentUser, Database, fail
from app.auth.models import AuthSession, User
from app.auth.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.auth.service import COOKIE_NAME, authenticate, find_session, new_session, password_hasher

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def set_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def issue_login(
    request: Request, response: Response, db: Session, old_session: AuthSession, user: User
) -> AuthResponse:
    db.delete(old_session)
    session, token = new_session(db, request.app.state.settings.session_ttl_hours, user)
    result = AuthResponse(
        user=UserResponse.model_validate(user),
        csrf_token=session.csrf_token,
        redirect_url="/admin" if user.role == "admin" else "/",
    )
    db.commit()
    set_cookie(request, response, token)
    return result


@router.get("/csrf")
def csrf(request: Request, response: Response, db: Database) -> dict[str, str]:
    session = find_session(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        session, token = new_session(db, request.app.state.settings.session_ttl_hours)
        db.commit()
        set_cookie(request, response, token)
    return {"csrf_token": session.csrf_token}


@router.post("/register", status_code=201, response_model=AuthResponse)
def register(
    body: RegisterRequest, request: Request, response: Response, db: Database, session: CsrfSession
) -> AuthResponse:
    if session.user_id:
        fail(409, "ALREADY_AUTHENTICATED", "Вы уже вошли в аккаунт.")
    user = User(
        name=body.name,
        email=body.email,
        phone=body.phone,
        password_hash=password_hasher.hash(body.password),
        role="client",
        consent_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) in (
            "uq_users_email",
            "uq_users_phone",
        ):
            fail(409, "IDENTIFIER_ALREADY_EXISTS", "Этот телефон или email уже зарегистрирован.")
        raise
    response.headers["Location"] = "/api/v1/auth/me"
    return issue_login(request, response, db, session, user)


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: Database, session: CsrfSession
) -> AuthResponse:
    if session.user_id:
        fail(409, "ALREADY_AUTHENTICATED", "Вы уже вошли в аккаунт.")
    user = authenticate(db, body.identifier, body.password)
    if user is None:
        fail(401, "INVALID_CREDENTIALS", "Неверный телефон/email или пароль.")
    return issue_login(request, response, db, session, user)


@router.post("/logout", status_code=204)
def logout(response: Response, db: Database, session: CsrfSession) -> None:
    db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user
