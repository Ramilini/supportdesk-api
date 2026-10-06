from collections.abc import Generator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db, require_roles
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models.user import Role, User


@pytest.fixture
def rbac_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, test_session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_require_roles_returns_user_for_allowed_role() -> None:
    user = User(
        email="agent@example.com",
        hashed_password="unused",
        role=Role.AGENT,
    )
    check_role = require_roles(Role.AGENT, Role.ADMIN)

    assert check_role(current_user=user) is user


def test_require_roles_rejects_disallowed_role() -> None:
    user = User(
        email="customer@example.com",
        hashed_password="unused",
        role=Role.CUSTOMER,
    )
    check_role = require_roles(Role.AGENT, Role.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        check_role(current_user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient permissions"


def test_require_roles_requires_at_least_one_role() -> None:
    with pytest.raises(ValueError, match="At least one allowed role"):
        require_roles()


def test_user_role_column_defaults_to_customer_on_database() -> None:
    role_column = User.__table__.c.role

    assert role_column.nullable is False
    assert role_column.default is not None
    assert role_column.default.arg is Role.CUSTOMER
    assert role_column.server_default is not None
    assert role_column.server_default.arg == Role.CUSTOMER.value


def test_database_assigns_customer_when_role_is_omitted(
    rbac_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, test_session_factory = rbac_client
    with test_session_factory() as db:
        db.execute(
            text(
                "INSERT INTO users (email, hashed_password) "
                "VALUES ('default-role@example.com', 'unused')"
            )
        )
        db.commit()
        user = db.scalar(
            select(User).where(User.email == "default-role@example.com")
        )

    assert user is not None
    assert user.role is Role.CUSTOMER


@pytest.mark.parametrize(
    ("path", "role", "expected_status"),
    [
        ("/users/me", Role.CUSTOMER, 200),
        ("/users/me", Role.AGENT, 200),
        ("/users/me", Role.ADMIN, 200),
        ("/users/", Role.CUSTOMER, 403),
        ("/users/", Role.AGENT, 200),
        ("/users/", Role.ADMIN, 200),
    ],
)
def test_protected_user_routes_enforce_roles(
    rbac_client: tuple[TestClient, sessionmaker[Session]],
    path: str,
    role: Role,
    expected_status: int,
) -> None:
    client, test_session_factory = rbac_client
    email = f"{role.value.lower()}@example.com"
    with test_session_factory() as db:
        db.add(User(email=email, hashed_password="unused", role=role))
        db.commit()

    token = create_access_token(email)
    response = client.get(
        path,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == expected_status
    if expected_status == 200 and path == "/users/me":
        assert response.json()["email"] == email
    elif expected_status == 200:
        assert [user["email"] for user in response.json()] == [email]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/users/me"),
        ("get", "/users/"),
        ("patch", "/users/1/role"),
    ],
)
def test_protected_user_routes_require_authentication(
    rbac_client: tuple[TestClient, sessionmaker[Session]],
    method: str,
    path: str,
) -> None:
    client, _ = rbac_client

    if method == "patch":
        response = client.patch(path, json={"role": "AGENT"})
    else:
        response = client.get(path)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.CUSTOMER, 403),
        (Role.AGENT, 403),
        (Role.ADMIN, 200),
    ],
)
def test_role_update_requires_admin(
    rbac_client: tuple[TestClient, sessionmaker[Session]],
    role: Role,
    expected_status: int,
) -> None:
    client, test_session_factory = rbac_client
    target = User(
        email="target@example.com",
        hashed_password="unused",
        role=Role.CUSTOMER,
    )
    requester = User(
        email=f"{role.value.lower()}@example.com",
        hashed_password="unused",
        role=role,
    )
    requester_email = requester.email
    with test_session_factory() as db:
        db.add_all([target, requester])
        db.commit()
        target_id = target.id

    token = create_access_token(requester_email)
    response = client.patch(
        f"/users/{target_id}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "AGENT"},
    )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["role"] == Role.AGENT.value

    with test_session_factory() as db:
        updated_target = db.get(User, target_id)
        assert updated_target is not None
        expected_role = Role.AGENT if role is Role.ADMIN else Role.CUSTOMER
        assert updated_target.role is expected_role


def test_role_update_returns_not_found_for_missing_user(
    rbac_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, test_session_factory = rbac_client
    admin = User(
        email="admin@example.com",
        hashed_password="unused",
        role=Role.ADMIN,
    )
    admin_email = admin.email
    with test_session_factory() as db:
        db.add(admin)
        db.commit()

    token = create_access_token(admin_email)
    response = client.patch(
        "/users/999/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "AGENT"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_role_update_rejects_unknown_role(
    rbac_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, test_session_factory = rbac_client
    admin = User(
        email="admin@example.com",
        hashed_password="unused",
        role=Role.ADMIN,
    )
    admin_email = admin.email
    target = User(
        email="target@example.com",
        hashed_password="unused",
        role=Role.CUSTOMER,
    )
    with test_session_factory() as db:
        db.add_all([admin, target])
        db.commit()
        target_id = target.id

    token = create_access_token(admin_email)
    response = client.patch(
        f"/users/{target_id}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "SUPERUSER"},
    )

    assert response.status_code == 422
