from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models.user import Role, User


def test_user_model_constraints_and_timezone_fields() -> None:
    email_index = next(
        index
        for index in User.__table__.indexes
        if [column.name for column in index.columns] == ["email"]
    )

    assert email_index.unique is True
    assert User.__table__.c.created_at.type.timezone is True
    assert User.__table__.c.updated_at.type.timezone is True
    assert {role.value for role in Role} == {"CUSTOMER", "AGENT", "ADMIN"}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def register_user(
    client: TestClient, email: str = "user@example.com"
) -> Response:
    return client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!"},
    )


def login_user(
    client: TestClient,
    email: str = "user@example.com",
    password: str = "Password123!",
) -> Response:
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def test_register_user_and_reject_duplicate(client: TestClient) -> None:
    response = register_user(client)

    assert response.status_code == 201
    response_data = response.json()
    assert response_data["email"] == "user@example.com"
    assert response_data["role"] == "CUSTOMER"
    assert "password" not in response_data
    assert "hashed_password" not in response_data
    assert "updated_at" in response_data
    assert response_data["is_active"] is True

    duplicate_response = register_user(client)
    assert duplicate_response.status_code == 400


def test_registration_does_not_allow_role_escalation(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": "agent@example.com",
            "password": "Password123!",
            "role": "AGENT",
        },
    )

    assert response.status_code == 422


def test_login_with_valid_credentials_and_get_customer_profile(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201

    login_response = login_user(client)
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    profile_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["email"] == "user@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("user@example.com", "incorrect-password"),
        ("missing@example.com", "Password123!"),
    ],
)
def test_login_rejects_invalid_credentials_without_disclosing_user(
    client: TestClient,
    email: str,
    password: str,
) -> None:
    assert register_user(client).status_code == 201

    response = login_user(client, email=email, password=password)

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode(
            {
                "sub": "user@example.com",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            "not-the-configured-secret",
            algorithm="HS256",
        ),
        create_access_token(
            "user@example.com",
            expires_delta=timedelta(seconds=-1),
        ),
    ],
    ids=["malformed", "bad-signature", "expired"],
)
def test_get_current_user_rejects_invalid_or_expired_jwt(
    client: TestClient,
    token: str,
) -> None:
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_get_current_user_rejects_inactive_user(client: TestClient) -> None:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        user = User(
            email="inactive@example.com",
            hashed_password="unused",
            is_active=False,
        )
        db.add(user)
        db.commit()
    finally:
        db_generator.close()

    token = create_access_token("inactive@example.com")
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.CUSTOMER, 200),
        (Role.AGENT, 200),
        (Role.ADMIN, 200),
    ],
)
def test_user_profile_requires_agent_or_admin(
    client: TestClient,
    role: Role,
    expected_status: int,
) -> None:
    email = f"{role.value.lower()}@example.com"
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        db.add(User(email=email, hashed_password="unused", role=role))
        db.commit()
    finally:
        db_generator.close()

    token = create_access_token(email)
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.CUSTOMER, 403),
        (Role.AGENT, 200),
        (Role.ADMIN, 200),
    ],
)
def test_list_users_requires_agent_or_admin(
    client: TestClient,
    role: Role,
    expected_status: int,
) -> None:
    email = f"{role.value.lower()}@example.com"
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        db.add(User(email=email, hashed_password="unused", role=role))
        db.commit()
    finally:
        db_generator.close()

    token = create_access_token(email)
    response = client.get(
        "/users/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert [user["email"] for user in response.json()] == [email]
