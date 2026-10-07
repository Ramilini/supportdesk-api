from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import Role, User


@pytest.fixture
def ticket_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
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


def create_user(
    session_factory: sessionmaker[Session], email: str, role: Role
) -> int:
    with session_factory() as db:
        user = User(email=email, hashed_password="unused", role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def auth_headers(email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(email)}"}


def create_ticket(
    session_factory: sessionmaker[Session],
    owner_id: int,
    *,
    title: str = "Ticket",
    status: TicketStatus = TicketStatus.OPEN,
    priority: TicketPriority = TicketPriority.MEDIUM,
) -> int:
    with session_factory() as db:
        ticket = Ticket(
            title=title,
            description="Ticket description",
            status=status,
            priority=priority,
            owner_id=owner_id,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        return ticket.id


def test_customer_creates_ticket_with_owning_user(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    email = "customer@example.com"
    owner_id = create_user(session_factory, email, Role.CUSTOMER)

    response = client.post(
        "/tickets",
        headers=auth_headers(email),
        json={
            "title": "Cannot sign in",
            "description": "Password reset is not arriving.",
            "priority": "HIGH",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Cannot sign in"
    assert data["status"] == TicketStatus.OPEN.value
    assert data["priority"] == TicketPriority.HIGH.value
    assert data["owner_id"] == owner_id
    assert data["created_at"]


def test_customer_only_lists_and_reads_own_tickets(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    owner_email = "owner@example.com"
    other_email = "other@example.com"
    owner_id = create_user(session_factory, owner_email, Role.CUSTOMER)
    other_id = create_user(session_factory, other_email, Role.CUSTOMER)
    own_ticket_id = create_ticket(session_factory, owner_id, title="Mine")
    other_ticket_id = create_ticket(session_factory, other_id, title="Theirs")

    response = client.get("/tickets", headers=auth_headers(owner_email))
    assert response.status_code == 200
    assert [ticket["id"] for ticket in response.json()] == [own_ticket_id]

    forbidden_response = client.get(
        f"/tickets/{other_ticket_id}",
        headers=auth_headers(owner_email),
    )
    assert forbidden_response.status_code == 403


def test_customer_cannot_update_another_customers_ticket(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    owner_email = "owner@example.com"
    owner_id = create_user(session_factory, owner_email, Role.CUSTOMER)
    other_id = create_user(session_factory, "other@example.com", Role.CUSTOMER)
    ticket_id = create_ticket(session_factory, other_id)

    response = client.patch(
        f"/tickets/{ticket_id}",
        headers=auth_headers(owner_email),
        json={"title": "Unauthorized edit"},
    )

    assert response.status_code == 403
    with session_factory() as db:
        ticket = db.get(Ticket, ticket_id)
        assert ticket is not None
        assert ticket.owner_id == other_id
        assert ticket.title == "Ticket"


def test_customer_can_edit_own_open_ticket_or_close_it(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    email = "customer@example.com"
    user_id = create_user(session_factory, email, Role.CUSTOMER)
    ticket_id = create_ticket(session_factory, user_id)
    headers = auth_headers(email)

    edit_response = client.patch(
        f"/tickets/{ticket_id}",
        headers=headers,
        json={"title": "Updated title", "priority": "HIGH"},
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["title"] == "Updated title"

    close_response = client.patch(
        f"/tickets/{ticket_id}",
        headers=headers,
        json={"status": "CLOSED"},
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == TicketStatus.CLOSED.value

    rejected_response = client.patch(
        f"/tickets/{ticket_id}",
        headers=headers,
        json={"title": "Closed tickets cannot be edited"},
    )
    assert rejected_response.status_code == 403


def test_agent_can_view_and_filter_all_tickets(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    first_id = create_user(
        session_factory, "first@example.com", Role.CUSTOMER
    )
    second_id = create_user(
        session_factory, "second@example.com", Role.CUSTOMER
    )
    create_user(session_factory, "agent@example.com", Role.AGENT)
    first_ticket = create_ticket(
        session_factory, first_id, title="Open ticket"
    )
    second_ticket = create_ticket(
        session_factory,
        second_id,
        title="Resolved ticket",
        status=TicketStatus.RESOLVED,
        priority=TicketPriority.HIGH,
    )
    headers = auth_headers("agent@example.com")

    all_response = client.get("/tickets", headers=headers)
    assert all_response.status_code == 200
    assert {item["id"] for item in all_response.json()} == {
        first_ticket,
        second_ticket,
    }

    filtered_response = client.get(
        "/tickets?status=RESOLVED",
        headers=headers,
    )
    assert filtered_response.status_code == 200
    assert [item["id"] for item in filtered_response.json()] == [
        second_ticket
    ]


def test_ticket_list_supports_pagination_and_priority_filter(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    email = "agent@example.com"
    owner_id = create_user(session_factory, "owner@example.com", Role.CUSTOMER)
    create_user(session_factory, email, Role.AGENT)
    ticket_ids = [
        create_ticket(
            session_factory,
            owner_id,
            title=f"Ticket {index}",
            priority=(
                TicketPriority.HIGH
                if index % 2
                else TicketPriority.LOW
            ),
        )
        for index in range(4)
    ]

    page_response = client.get(
        "/tickets?skip=1&limit=2",
        headers=auth_headers(email),
    )
    assert [item["id"] for item in page_response.json()] == ticket_ids[1:3]

    filtered_response = client.get(
        "/tickets?priority=HIGH",
        headers=auth_headers(email),
    )
    assert [item["title"] for item in filtered_response.json()] == [
        "Ticket 1",
        "Ticket 3",
    ]


def test_agent_can_update_any_ticket(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = ticket_client
    owner_id = create_user(session_factory, "owner@example.com", Role.CUSTOMER)
    create_user(session_factory, "agent@example.com", Role.AGENT)
    ticket_id = create_ticket(session_factory, owner_id)

    response = client.patch(
        f"/tickets/{ticket_id}",
        headers=auth_headers("agent@example.com"),
        json={"status": "IN_PROGRESS", "priority": "URGENT"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == TicketStatus.IN_PROGRESS.value
    assert response.json()["priority"] == TicketPriority.URGENT.value


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/tickets",
            {"title": "Bad", "description": "Bad", "priority": "ASAP"},
        ),
        ("get", "/tickets?status=WAITING", None),
        ("patch", "/tickets/1", {"status": "WAITING"}),
        ("patch", "/tickets/1", {"title": None}),
    ],
)
def test_ticket_endpoints_reject_invalid_enums(
    ticket_client: tuple[TestClient, sessionmaker[Session]],
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    client, session_factory = ticket_client
    email = "agent@example.com"
    create_user(session_factory, email, Role.AGENT)
    request = getattr(client, method)
    if payload is None:
        response = request(path, headers=auth_headers(email))
    else:
        response = request(
            path,
            headers=auth_headers(email),
            json=payload,
        )

    assert response.status_code == 422
