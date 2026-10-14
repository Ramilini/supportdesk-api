from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.comment import Comment
from app.models.ticket import Ticket
from app.models.user import Role, User


@pytest.fixture
def comments_client(
    db_engine,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

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
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def create_user(
    session_factory: sessionmaker[Session],
    email: str,
    role: Role,
    *,
    is_active: bool = True,
) -> int:
    with session_factory() as db:
        user = User(
            email=email,
            hashed_password="unused",
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def create_ticket(
    session_factory: sessionmaker[Session],
    owner_id: int,
) -> int:
    with session_factory() as db:
        ticket = Ticket(
            title="Ticket",
            description="Ticket description",
            owner_id=owner_id,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        return ticket.id


def auth_headers(email: str) -> dict[str, str]:
    token = create_access_token(email)
    return {"Authorization": f"Bearer {token}"}


def test_customer_can_comment_on_own_ticket_but_not_another_customers(
    comments_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = comments_client
    owner_email = "owner@example.com"
    owner_id = create_user(session_factory, owner_email, Role.CUSTOMER)
    other_id = create_user(
        session_factory,
        "other@example.com",
        Role.CUSTOMER,
    )
    own_ticket_id = create_ticket(session_factory, owner_id)
    other_ticket_id = create_ticket(session_factory, other_id)
    headers = auth_headers(owner_email)

    create_response = client.post(
        f"/tickets/{own_ticket_id}/comments",
        headers=headers,
        json={"content": "I can reproduce this issue."},
    )
    assert create_response.status_code == 201
    comment = create_response.json()
    assert comment["content"] == "I can reproduce this issue."
    assert comment["ticket_id"] == own_ticket_id
    assert comment["author_id"] == owner_id

    list_response = client.get(
        f"/tickets/{own_ticket_id}/comments",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [comment["id"]]

    cross_customer_create = client.post(
        f"/tickets/{other_ticket_id}/comments",
        headers=headers,
        json={"content": "Unauthorized comment."},
    )
    cross_customer_list = client.get(
        f"/tickets/{other_ticket_id}/comments",
        headers=headers,
    )
    assert cross_customer_create.status_code == 403
    assert cross_customer_list.status_code == 403


@pytest.mark.parametrize("role", [Role.AGENT, Role.ADMIN])
def test_agents_and_admins_can_comment_on_any_ticket(
    comments_client: tuple[TestClient, sessionmaker[Session]],
    role: Role,
) -> None:
    client, session_factory = comments_client
    owner_id = create_user(
        session_factory,
        "owner@example.com",
        Role.CUSTOMER,
    )
    requester_email = f"{role.value.lower()}@example.com"
    create_user(session_factory, requester_email, role)
    ticket_id = create_ticket(session_factory, owner_id)

    response = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=auth_headers(requester_email),
        json={"content": f"Note from {role.value}."},
    )

    assert response.status_code == 201
    assert response.json()["content"] == f"Note from {role.value}."
    assert client.get(
        f"/tickets/{ticket_id}/comments",
        headers=auth_headers(requester_email),
    ).status_code == 200


@pytest.mark.parametrize("role", [Role.AGENT, Role.ADMIN])
def test_agent_and_admin_can_assign_ticket_to_active_agent(
    comments_client: tuple[TestClient, sessionmaker[Session]],
    role: Role,
) -> None:
    client, session_factory = comments_client
    owner_id = create_user(
        session_factory,
        "owner@example.com",
        Role.CUSTOMER,
    )
    requester_email = f"{role.value.lower()}@example.com"
    create_user(session_factory, requester_email, role)
    agent_id = create_user(
        session_factory,
        "assignee@example.com",
        Role.AGENT,
    )
    ticket_id = create_ticket(session_factory, owner_id)

    response = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=auth_headers(requester_email),
        json={"assigned_to_id": agent_id},
    )

    assert response.status_code == 200
    assert response.json()["assigned_to_id"] == agent_id
    with session_factory() as db:
        ticket = db.get(Ticket, ticket_id)
        assert ticket is not None
        assert ticket.assigned_to is not None
        assert ticket.assigned_to.role is Role.AGENT


def test_customer_cannot_assign_tickets(
    comments_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = comments_client
    customer_email = "customer@example.com"
    owner_id = create_user(session_factory, customer_email, Role.CUSTOMER)
    agent_id = create_user(
        session_factory,
        "agent@example.com",
        Role.AGENT,
    )
    ticket_id = create_ticket(session_factory, owner_id)

    response = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=auth_headers(customer_email),
        json={"assigned_to_id": agent_id},
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("role", "is_active", "expected_status"),
    [
        (Role.CUSTOMER, True, 422),
        (Role.ADMIN, True, 422),
        (Role.AGENT, False, 422),
    ],
)
def test_assignment_requires_an_active_agent(
    comments_client: tuple[TestClient, sessionmaker[Session]],
    role: Role,
    is_active: bool,
    expected_status: int,
) -> None:
    client, session_factory = comments_client
    owner_id = create_user(
        session_factory,
        "owner@example.com",
        Role.CUSTOMER,
    )
    create_user(session_factory, "requester@example.com", Role.AGENT)
    assignee_id = create_user(
        session_factory,
        "assignee@example.com",
        role,
        is_active=is_active,
    )
    ticket_id = create_ticket(session_factory, owner_id)

    response = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=auth_headers("requester@example.com"),
        json={"assigned_to_id": assignee_id},
    )

    assert response.status_code == expected_status


def test_assignment_rejects_missing_ticket_or_assignee_and_can_be_cleared(
    comments_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = comments_client
    owner_id = create_user(
        session_factory,
        "owner@example.com",
        Role.CUSTOMER,
    )
    create_user(session_factory, "agent@example.com", Role.AGENT)
    agent_id = create_user(
        session_factory,
        "assignee@example.com",
        Role.AGENT,
    )
    ticket_id = create_ticket(session_factory, owner_id)
    headers = auth_headers("agent@example.com")

    missing_ticket = client.patch(
        "/tickets/999/assign",
        headers=headers,
        json={"assigned_to_id": agent_id},
    )
    missing_assignee = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=headers,
        json={"assigned_to_id": 999},
    )
    assert missing_ticket.status_code == 404
    assert missing_assignee.status_code == 404

    assign_response = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=headers,
        json={"assigned_to_id": agent_id},
    )
    clear_response = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=headers,
        json={"assigned_to_id": None},
    )
    assert assign_response.status_code == 200
    assert clear_response.status_code == 200
    assert clear_response.json()["assigned_to_id"] is None


def test_ticket_and_assignee_deletions_preserve_cascade_constraints(
    comments_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = comments_client
    owner_id = create_user(
        session_factory,
        "owner@example.com",
        Role.CUSTOMER,
    )
    agent_id = create_user(
        session_factory,
        "agent@example.com",
        Role.AGENT,
    )
    ticket_id = create_ticket(session_factory, owner_id)
    with session_factory() as db:
        ticket = db.get(Ticket, ticket_id)
        assert ticket is not None
        ticket.assigned_to_id = agent_id
        comment = Comment(
            ticket_id=ticket_id,
            author_id=owner_id,
            content="Test cascade.",
        )
        agent_comment = Comment(
            ticket_id=ticket_id,
            author_id=agent_id,
            content="Agent comment.",
        )
        db.add_all([comment, agent_comment])
        db.commit()
        comment_id = comment.id
        agent_comment_id = agent_comment.id

    with session_factory() as db:
        db.delete(db.get(User, agent_id))
        db.commit()
        ticket = db.get(Ticket, ticket_id)
        assert ticket is not None
        assert ticket.assigned_to_id is None
        assert db.scalar(
            select(Comment.id).where(Comment.id == agent_comment_id)
        ) is None

        db.delete(ticket)
        db.commit()
        assert db.scalar(
            select(Comment.id).where(Comment.id == comment_id)
        ) is None
