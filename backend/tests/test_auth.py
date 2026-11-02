from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin, require_client
from app.auth.models import AuthSession, User
from app.auth.service import COOKIE_NAME, token_hash
from scripts.create_admin import create_admin

PASSWORD = "Demo-password-123"
REGISTER = {"name": "Анна", "email": "anna@example.ru", "password": PASSWORD, "consent": True}


@pytest.fixture
def client(database):
    from app.main import create_app

    with TestClient(create_app(database[1])) as client:
        yield client


def csrf(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def register(client, **changes):
    return client.post("/api/v1/auth/register", json=REGISTER | changes, headers=csrf(client))


def logout(client):
    return client.post("/api/v1/auth/logout", headers=csrf(client))


def test_registration_creates_client_rotates_session_and_logs_in(client, database):
    headers = csrf(client)
    old_cookie = client.cookies.get(COOKIE_NAME)
    response = client.post("/api/v1/auth/register", json=REGISTER, headers=headers)
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "client"
    assert response.json()["redirect_url"] == "/"
    assert response.headers["location"] == "/api/v1/auth/me"
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert client.cookies.get(COOKIE_NAME) != old_cookie
    assert client.get("/api/v1/auth/me").json()["email"] == "anna@example.ru"
    with Session(database[0]) as db:
        user = db.scalar(select(User))
        assert user.consent_at is not None
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1
        assert (
            db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(old_cookie)))
            is None
        )
        assert db.scalar(select(AuthSession)).token_hash != client.cookies.get(COOKIE_NAME)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "contact,identifier",
    [
        ({"email": " ANNA@EXAMPLE.RU "}, "anna@example.ru"),
        ({"email": None, "phone": "+7 (999) 000-00-01"}, "+79990000001"),
    ],
)
def test_login_normalizes_contacts_and_logout_revokes_session(client, contact, identifier):
    assert register(client, **contact).status_code == 201
    assert logout(client).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": PASSWORD},
        headers=csrf(client),
    )
    assert response.status_code == 200
    token = client.cookies.get(COOKIE_NAME)
    assert logout(client).status_code == 204
    assert (
        client.get("/api/v1/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code
        == 401
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"password": "short"},
        {"password": "x" * 129},
        {"email": "invalid"},
        {"email": None},
        {"phone": "+7 999"},
        {"consent": False},
        {"consent": "true"},
        {"role": "admin"},
    ],
)
def test_invalid_registration_does_not_create_user(client, database, changes):
    response = register(client, **changes)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert PASSWORD not in response.text
    with Session(database[0]) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0


def test_consent_is_required(client):
    payload = {key: value for key, value in REGISTER.items() if key != "consent"}
    assert (
        client.post("/api/v1/auth/register", json=payload, headers=csrf(client)).status_code == 422
    )


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("register", REGISTER),
        ("login", {"identifier": "anna@example.ru", "password": PASSWORD}),
        ("logout", None),
    ],
)
def test_mutations_require_csrf(client, endpoint, payload):
    assert client.post(f"/api/v1/auth/{endpoint}", json=payload).status_code == 403
    headers = csrf(client) | {"Origin": "https://other.example"}
    assert client.post(f"/api/v1/auth/{endpoint}", json=payload, headers=headers).status_code == 403


def test_duplicate_contact_and_generic_login_error(client):
    assert register(client).status_code == 201
    assert logout(client).status_code == 204
    assert register(client, email="ANNA@example.ru").status_code == 409
    failures = []
    for identifier in ["anna@example.ru", "unknown@example.ru", "invalid"]:
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": identifier, "password": "wrong"},
            headers=csrf(client),
        )
        assert response.status_code == 401
        failures.append(response.json())
    assert failures[0] == failures[1] == failures[2]


def test_expired_session_cannot_authenticate_or_mutate(client, database):
    assert register(client).status_code == 201
    headers = csrf(client)
    with database[0].begin() as connection:
        connection.execute(
            update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    assert csrf(client) != headers


def test_server_role_guards_and_admin_creation(client, database):
    client.app.get("/test/admin", dependencies=[Depends(require_admin)])(lambda: {"ok": True})
    client.app.get("/test/client", dependencies=[Depends(require_client)])(lambda: {"ok": True})
    assert client.get("/test/admin").status_code == 401
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert register(client).status_code == 201
    assert client.get("/test/admin").status_code == 403
    assert client.get("/test/client").status_code == 200
    assert client.get("/admin").status_code == 403
    with Session(database[0]) as db, db.begin():
        with pytest.raises(ValueError, match="клиенту"):
            create_admin(db, "Администратор", "anna@example.ru", PASSWORD)
        assert create_admin(db, "Администратор", "admin@lumenbook.ru", PASSWORD)
        assert not create_admin(db, "Администратор", "admin@lumenbook.ru", "another-password")
    assert logout(client).status_code == 204
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin@lumenbook.ru", "password": PASSWORD},
        headers=csrf(client),
    )
    assert response.status_code == 200
    assert response.json()["redirect_url"] == "/admin"
    assert client.get("/test/admin").status_code == 200
    assert client.get("/test/client").status_code == 403
    assert client.get("/admin").status_code == 200
    assert client.get("/login", follow_redirects=False).headers["location"] == "/admin"


def test_concurrent_registration_has_one_winner(database):
    from app.main import create_app

    with (
        TestClient(create_app(database[1])) as first,
        TestClient(create_app(database[1])) as second,
    ):
        first_headers, second_headers = csrf(first), csrf(second)
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [
                pool.submit(c.post, "/api/v1/auth/register", json=REGISTER, headers=h)
                for c, h in [(first, first_headers), (second, second_headers)]
            ]
            assert sorted(request.result().status_code for request in requests) == [201, 409]
    with Session(database[0]) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_secure_cookie_and_authenticated_conflicts(database):
    from app.main import create_app

    settings = database[1].model_copy(update={"session_cookie_secure": True})
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        response = register(client)
        assert response.status_code == 201
        assert "; secure" in response.headers["set-cookie"].lower()
        assert client.get("/api/v1/auth/me").status_code == 200
        assert register(client).status_code == 409
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "anna@example.ru", "password": PASSWORD},
                headers=csrf(client),
            ).status_code
            == 409
        )


def test_duplicate_formatted_phone_and_xss_escaping(client):
    assert (
        register(
            client, email=None, phone="+7 (999) 000-00-01", name="<script>x</script>"
        ).status_code
        == 201
    )
    assert "&lt;script&gt;x&lt;/script&gt;" in client.get("/").text
    assert logout(client).status_code == 204
    assert register(client, email=None, phone="+79990000001").status_code == 409


def test_malformed_origin_is_rejected(client):
    headers = csrf(client) | {"Origin": "http://[invalid"}
    assert client.post("/api/v1/auth/register", json=REGISTER, headers=headers).status_code == 403
