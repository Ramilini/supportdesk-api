import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import Role, User


def test_customer_creates_ticket_with_server_owned_fields(
    client: TestClient,
    customer_headers: dict[str, str],
    customer_user: User,
) -> None:
    response = client.post(
        "/tickets",
        headers=customer_headers,
        json={
            "title": "Cannot sign in",
            "description": "Password reset is not arriving.",
            "priority": TicketPriority.HIGH.value,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Cannot sign in"
    assert data["status"] == TicketStatus.OPEN.value
    assert data["priority"] == TicketPriority.HIGH.value
    assert data["owner_id"] == customer_user.id
    assert data["created_at"]


def test_customer_list_is_isolated_and_cannot_read_another_users_ticket(
    client: TestClient,
    customer_headers: dict[str, str],
    customer_user: User,
    make_user,
    make_ticket,
) -> None:
    own_ticket = make_ticket(customer_user, title="Mine")
    other_user = make_user("other@example.com")
    other_ticket = make_ticket(other_user, title="Not mine")

    response = client.get("/tickets", headers=customer_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [own_ticket.id]
    forbidden_response = client.get(
        f"/tickets/{other_ticket.id}",
        headers=customer_headers,
    )
    assert forbidden_response.status_code == 403


def test_customer_cannot_update_another_users_ticket(
    client: TestClient,
    db_session: Session,
    customer_headers: dict[str, str],
    make_user,
    make_ticket,
) -> None:
    owner = make_user("other@example.com")
    ticket = make_ticket(owner)

    response = client.patch(
        f"/tickets/{ticket.id}",
        headers=customer_headers,
        json={"title": "Unauthorized edit"},
    )

    assert response.status_code == 403
    db_session.refresh(ticket)
    assert ticket.title == "Support request"


def test_customer_can_update_open_ticket_and_close_it(
    client: TestClient,
    customer_headers: dict[str, str],
    customer_user: User,
    make_ticket,
) -> None:
    ticket = make_ticket(customer_user)

    edit_response = client.patch(
        f"/tickets/{ticket.id}",
        headers=customer_headers,
        json={"title": "Updated title", "priority": TicketPriority.HIGH.value},
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["title"] == "Updated title"

    close_response = client.patch(
        f"/tickets/{ticket.id}",
        headers=customer_headers,
        json={"status": TicketStatus.CLOSED.value},
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == TicketStatus.CLOSED.value

    edit_closed_response = client.patch(
        f"/tickets/{ticket.id}",
        headers=customer_headers,
        json={"title": "Closed tickets cannot be edited"},
    )
    assert edit_closed_response.status_code == 403


@pytest.mark.parametrize(
    "status",
    [TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED],
)
def test_customer_may_only_close_own_ticket(
    client: TestClient,
    customer_headers: dict[str, str],
    customer_user: User,
    make_ticket,
    status: TicketStatus,
) -> None:
    ticket = make_ticket(customer_user)

    response = client.patch(
        f"/tickets/{ticket.id}",
        headers=customer_headers,
        json={"status": status.value},
    )

    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.AGENT, Role.ADMIN])
def test_staff_can_list_and_update_all_tickets(
    client: TestClient,
    headers_for,
    make_user,
    make_ticket,
    role: Role,
) -> None:
    staff = make_user(f"{role.value.lower()}@example.com", role)
    owner = make_user("owner@example.com")
    ticket = make_ticket(owner)

    list_response = client.get("/tickets", headers=headers_for(staff.email))
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [ticket.id]

    update_response = client.patch(
        f"/tickets/{ticket.id}",
        headers=headers_for(staff.email),
        json={
            "status": TicketStatus.IN_PROGRESS.value,
            "priority": TicketPriority.URGENT.value,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == TicketStatus.IN_PROGRESS.value
    assert update_response.json()["priority"] == TicketPriority.URGENT.value


def test_ticket_list_filters_orders_and_paginates(
    client: TestClient,
    agent_headers: dict[str, str],
    customer_user: User,
    make_ticket,
) -> None:
    tickets = [
        make_ticket(
            customer_user,
            title=f"Ticket {index}",
            status=TicketStatus.RESOLVED if index == 2 else TicketStatus.OPEN,
            priority=TicketPriority.HIGH if index % 2 else TicketPriority.LOW,
        )
        for index in range(4)
    ]

    page = client.get(
        "/tickets?skip=1&limit=2",
        headers=agent_headers,
    )
    assert [item["id"] for item in page.json()] == [
        tickets[1].id,
        tickets[2].id,
    ]

    filtered = client.get(
        "/tickets?status=RESOLVED&priority=LOW",
        headers=agent_headers,
    )
    assert [item["id"] for item in filtered.json()] == [tickets[2].id]


def test_get_ticket_returns_not_found_for_missing_id(
    client: TestClient,
    customer_headers: dict[str, str],
) -> None:
    response = client.get("/tickets/999", headers=customer_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Ticket not found"


def test_update_ticket_returns_not_found_for_missing_id(
    client: TestClient,
    agent_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/tickets/999",
        headers=agent_headers,
        json={"title": "Updated"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/tickets", {"title": "", "description": "Details"}),
        (
            "post",
            "/tickets",
            {"title": "Valid", "description": "Details", "priority": "ASAP"},
        ),
        (
            "post",
            "/tickets",
            {"title": "Valid", "description": "Details", "owner_id": 123},
        ),
        ("patch", "/tickets/1", {"status": "WAITING"}),
        ("patch", "/tickets/1", {"title": None}),
    ],
)
def test_ticket_endpoints_reject_invalid_payloads(
    client: TestClient,
    agent_headers: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, object],
) -> None:
    response = getattr(client, method)(
        path,
        headers=agent_headers,
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "query",
    ["?skip=-1", "?limit=0", "?limit=101", "?status=WAITING", "?priority=ASAP"],
)
def test_ticket_list_rejects_invalid_filters(
    client: TestClient,
    agent_headers: dict[str, str],
    query: str,
) -> None:
    response = client.get(f"/tickets{query}", headers=agent_headers)

    assert response.status_code == 422


def test_agent_can_access_ticket_owned_by_another_customer(
    client: TestClient,
    agent_headers: dict[str, str],
    make_user,
    make_ticket,
) -> None:
    customer = make_user("owner@example.com")
    ticket = make_ticket(customer)

    response = client.get(f"/tickets/{ticket.id}", headers=agent_headers)

    assert response.status_code == 200
    assert response.json()["owner_id"] == customer.id
