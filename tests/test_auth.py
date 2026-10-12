from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import Role, User


def register(
    client: TestClient,
    email: str = "user@example.com",
    password: str = "Password123!",
):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )


def test_register_creates_customer_without_exposing_password(
    client: TestClient,
    db_session: Session,
) -> None:
    response = register(client)

    assert response.status_code == 201
    user_data = response.json()
    assert user_data["email"] == "user@example.com"
    assert user_data["role"] == Role.CUSTOMER.value
    assert user_data["is_active"] is True
    assert "password" not in user_data
    assert "hashed_password" not in user_data
    user = db_session.scalar(
        select(User).where(User.email == "user@example.com")
    )
    assert user is not None
    assert user.hashed_password != "Password123!"


def test_registration_rejects_duplicate_email(client: TestClient) -> None:
    assert register(client).status_code == 201

    response = register(client)

    assert response.status_code == 400
    assert response.json()["detail"] == "User with this email already exists"


def test_registration_handles_duplicate_detected_during_commit(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(db_session, "scalar", Mock(side_effect=[None, 1]))
    monkeypatch.setattr(
        db_session,
        "commit",
        Mock(side_effect=IntegrityError("insert", {}, Exception("duplicate"))),
    )

    response = register(client)

    assert response.status_code == 400
    assert response.json()["detail"] == "User with this email already exists"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "Password123!"},
        {"email": "new@example.com", "password": "short"},
        {"email": "new@example.com", "password": "a" * 73},
        {
            "email": "new@example.com",
            "password": "Password123!",
            "role": "ADMIN",
        },
        {"email": "new@example.com"},
    ],
)
def test_registration_rejects_invalid_payloads(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    assert client.post("/auth/register", json=payload).status_code == 422


def test_login_returns_bearer_token_and_token_authenticates(
    client: TestClient,
) -> None:
    assert register(client).status_code == 201

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "Password123!"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    profile = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == "user@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("user@example.com", "incorrect-password"),
        ("missing@example.com", "Password123!"),
    ],
)
def test_login_rejects_invalid_credentials(
    client: TestClient,
    email: str,
    password: str,
) -> None:
    assert register(client).status_code == 201

    response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode(
            {
                "sub": "user@example.com",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            "incorrect-signing-key",
            algorithm="HS256",
        ),
        create_access_token(
            "user@example.com",
            expires_delta=timedelta(seconds=-1),
        ),
        jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            settings.secret_key.get_secret_value(),
            algorithm=settings.algorithm,
        ),
    ],
    ids=["malformed", "bad-signature", "expired", "missing-subject"],
)
def test_profile_rejects_invalid_tokens(
    client: TestClient,
    token: str,
) -> None:
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_profile_rejects_inactive_user(
    client: TestClient,
    make_user,
    headers_for,
) -> None:
    make_user("inactive@example.com", is_active=False)

    response = client.get(
        "/users/me",
        headers=headers_for("inactive@example.com"),
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/users/me", None),
        ("get", "/users/", None),
        ("get", "/tickets", None),
        (
            "post",
            "/tickets",
            {"title": "Unauthenticated", "description": "Must be rejected."},
        ),
        ("patch", "/users/1/role", {"role": "AGENT"}),
        ("patch", "/tickets/1", {"title": "Must be rejected."}),
    ],
)
def test_protected_route_requires_credentials(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    request = getattr(client, method)
    if payload is None:
        response = request(path)
    else:
        response = request(path, json=payload)

    assert response.status_code == 401
