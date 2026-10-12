import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.models.user import Role, User


def test_require_roles_allows_configured_role(make_user) -> None:
    agent = make_user("agent@example.com", Role.AGENT)

    assert require_roles(Role.AGENT, Role.ADMIN)(current_user=agent) is agent


def test_require_roles_rejects_disallowed_role(make_user) -> None:
    customer = make_user("customer@example.com", Role.CUSTOMER)

    with pytest.raises(HTTPException) as exc_info:
        require_roles(Role.AGENT, Role.ADMIN)(current_user=customer)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient permissions"


def test_require_roles_requires_at_least_one_role() -> None:
    with pytest.raises(ValueError, match="At least one allowed role"):
        require_roles()


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.CUSTOMER, 403),
        (Role.AGENT, 200),
        (Role.ADMIN, 200),
    ],
)
def test_user_list_requires_agent_or_admin(
    client: TestClient,
    make_user,
    headers_for,
    role: Role,
    expected_status: int,
) -> None:
    user = make_user(f"{role.value.lower()}@example.com", role)

    response = client.get("/users/", headers=headers_for(user.email))

    assert response.status_code == expected_status
    if expected_status == 200:
        assert [item["email"] for item in response.json()] == [user.email]


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.CUSTOMER, 403),
        (Role.AGENT, 403),
        (Role.ADMIN, 200),
    ],
)
def test_role_update_requires_admin(
    client: TestClient,
    db_session: Session,
    make_user,
    headers_for,
    role: Role,
    expected_status: int,
) -> None:
    requester = make_user(f"{role.value.lower()}@example.com", role)
    target = make_user("target@example.com")

    response = client.patch(
        f"/users/{target.id}/role",
        headers=headers_for(requester.email),
        json={"role": Role.AGENT.value},
    )

    assert response.status_code == expected_status
    db_session.expire_all()
    stored_target = db_session.get(User, target.id)
    assert stored_target is not None
    assert stored_target.role is (
        Role.AGENT if role is Role.ADMIN else Role.CUSTOMER
    )


def test_admin_role_update_returns_not_found_for_missing_user(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/users/999/role",
        headers=admin_headers,
        json={"role": Role.AGENT.value},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_admin_role_update_rejects_unknown_role(
    client: TestClient,
    admin_headers: dict[str, str],
    customer_user: User,
) -> None:
    response = client.patch(
        f"/users/{customer_user.id}/role",
        headers=admin_headers,
        json={"role": "SUPERUSER"},
    )

    assert response.status_code == 422


def test_user_listing_contains_all_roles_only_for_staff(
    client: TestClient,
    db_session: Session,
    customer_user: User,
    agent_headers: dict[str, str],
) -> None:
    db_session.add(
        User(
            email="administrator@example.com",
            hashed_password="unused",
            role=Role.ADMIN,
        )
    )
    db_session.flush()

    response = client.get("/users/", headers=agent_headers)

    assert response.status_code == 200
    assert {item["role"] for item in response.json()} == {
        Role.CUSTOMER.value,
        Role.AGENT.value,
        Role.ADMIN.value,
    }
    assert db_session.scalar(
        select(User).where(User.email == customer_user.email)
    ) is customer_user
